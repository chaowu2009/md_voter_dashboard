from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PARSED_DIR = Path("data/parsed")
REPORT_DIR = Path("data/validation_reports")

REQUIRED_COLUMNS = [
    "report_date",
    "county",
    "DEM",
    "REP",
    "UNA",
    "LIB",
    "GRN",
    "WCP",
    "NLM",
    "OTH",
    "TOTAL",
    "source_pdf",
    "parser_version",
]

PARTY_COLUMNS = ["DEM", "REP", "UNA", "LIB", "GRN", "WCP", "NLM", "OTH", "TOTAL"]
STATEWIDE_TOTAL_PCT_THRESHOLD = 0.10
STATEWIDE_TOTAL_ABS_THRESHOLD = 50000

EXPECTED_MD_COUNTIES = {
    "ALLEGANY",
    "ANNE ARUNDEL",
    "BALTIMORE CITY",
    "BALTIMORE CO.",
    "CALVERT",
    "CAROLINE",
    "CARROLL",
    "CECIL",
    "CHARLES",
    "DORCHESTER",
    "FREDERICK",
    "GARRETT",
    "HARFORD",
    "HOWARD",
    "KENT",
    "MONTGOMERY",
    "PR. GEORGE'S",
    "QUEEN ANNE'S",
    "ST. MARY'S",
    "SOMERSET",
    "TALBOT",
    "WASHINGTON",
    "WICOMICO",
    "WORCESTER",
}


@dataclass
class Issue:
    severity: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


def compute_score(issues: list[Issue]) -> int:
    penalties = {"critical": 20, "warning": 5, "informational": 1}
    total_penalty = sum(penalties.get(issue.severity, 0) for issue in issues)
    return max(0, 100 - total_penalty)


def normalize_party_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "UNA" not in df.columns and "UNAF" in df.columns:
        df = df.rename(columns={"UNAF": "UNA"})
    return df


def extract_report_date(df: pd.DataFrame, csv_path: Path) -> pd.Timestamp | None:
    if "report_date" in df.columns:
        parsed = pd.to_datetime(df["report_date"], errors="coerce").dropna()
        if not parsed.empty:
            return parsed.iloc[0]

    match = re.search(r"(\d{4})_(\d{2})", csv_path.stem)
    if not match:
        return None
    year, month = match.groups()
    return pd.Timestamp(year=int(year), month=int(month), day=1)


def validate_file(csv_path: Path) -> dict[str, object]:
    issues: list[Issue] = []
    report_date: pd.Timestamp | None = None
    statewide_total: float | None = None

    try:
        df = pd.read_csv(csv_path)
        df = normalize_party_columns(df)
        report_date = extract_report_date(df, csv_path)
    except Exception as exc:  # noqa: BLE001
        issues.append(Issue("critical", "file_read_error", f"Could not read CSV: {exc}"))
        return {
            "file": csv_path.name,
            "row_count": 0,
            "parser_quality_score": compute_score(issues),
            "issues": [issue.as_dict() for issue in issues],
            "_report_date": None,
            "_statewide_total": None,
        }

    missing_required = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_required:
        issues.append(
            Issue(
                "critical",
                "missing_required_columns",
                f"Missing required columns: {', '.join(missing_required)}",
            )
        )
        return {
            "file": csv_path.name,
            "row_count": len(df),
            "parser_quality_score": compute_score(issues),
            "issues": [issue.as_dict() for issue in issues],
            "_report_date": report_date.isoformat() if report_date is not None else None,
            "_statewide_total": None,
        }

    # Numeric validation for party columns when values are present.
    for col in PARTY_COLUMNS:
        numeric = pd.to_numeric(df[col], errors="coerce")
        invalid_mask = df[col].notna() & numeric.isna()
        invalid_count = int(invalid_mask.sum())
        if invalid_count > 0:
            issues.append(
                Issue(
                    "critical",
                    "invalid_numeric_field",
                    f"Column {col} has {invalid_count} non-numeric non-null values.",
                )
            )

    total_series = pd.to_numeric(df["TOTAL"], errors="coerce")
    statewide_total = float(total_series.sum(skipna=True))

    # Null values are allowed if a party is missing in source PDF.
    null_summary = {col: int(df[col].isna().sum()) for col in PARTY_COLUMNS}
    if any(v > 0 for v in null_summary.values()):
        issues.append(
            Issue(
                "informational",
                "allowed_null_party_counts",
                f"Null party-count values observed (allowed): {null_summary}",
            )
        )

    # Expected counties check.
    seen_counties = {str(c).strip().upper() for c in df["county"].dropna().unique()}
    missing_counties = sorted(EXPECTED_MD_COUNTIES - seen_counties)
    extra_counties = sorted(seen_counties - EXPECTED_MD_COUNTIES)
    if missing_counties:
        issues.append(
            Issue(
                "warning",
                "missing_expected_counties",
                f"Missing expected counties: {', '.join(missing_counties)}",
            )
        )
    if extra_counties:
        issues.append(
            Issue(
                "warning",
                "unexpected_counties",
                f"Unexpected county names: {', '.join(extra_counties)}",
            )
        )

    # Known party codes availability check in schema.
    missing_party_columns = [col for col in PARTY_COLUMNS if col not in df.columns]
    if missing_party_columns:
        issues.append(
            Issue(
                "critical",
                "missing_known_party_columns",
                f"Missing known party columns: {', '.join(missing_party_columns)}",
            )
        )

    # Uniqueness check for report_date + county.
    duplicate_mask = df.duplicated(subset=["report_date", "county"], keep=False)
    duplicate_count = int(duplicate_mask.sum())
    if duplicate_count > 0:
        issues.append(
            Issue(
                "critical",
                "duplicate_keys",
                f"Found {duplicate_count} rows with duplicate keys (report_date + county).",
            )
        )

    return {
        "file": csv_path.name,
        "row_count": len(df),
        "parser_quality_score": compute_score(issues),
        "issues": [issue.as_dict() for issue in issues],
        "_report_date": report_date.isoformat() if report_date is not None else None,
        "_statewide_total": statewide_total,
    }


def add_statewide_continuity_checks(reports: list[dict[str, object]]) -> None:
    rows: list[dict[str, object]] = []
    for report in reports:
        report_date_raw = report.get("_report_date")
        statewide_total = report.get("_statewide_total")
        if report_date_raw is None or statewide_total is None:
            continue
        report_date = pd.to_datetime(report_date_raw, errors="coerce")
        if pd.isna(report_date):
            continue
        rows.append(
            {
                "file": report["file"],
                "report_date": report_date,
                "statewide_total": float(statewide_total),
            }
        )

    if len(rows) < 2:
        return

    timeline = pd.DataFrame(rows).sort_values("report_date").reset_index(drop=True)
    report_by_file = {str(r["file"]): r for r in reports}

    for i in range(1, len(timeline)):
        curr = timeline.iloc[i]
        prev = timeline.iloc[i - 1]
        prev_total = float(prev["statewide_total"])
        curr_total = float(curr["statewide_total"])
        if prev_total <= 0:
            continue

        pct_change = (curr_total - prev_total) / prev_total
        abs_change = abs(curr_total - prev_total)
        if abs(pct_change) <= STATEWIDE_TOTAL_PCT_THRESHOLD or abs_change < STATEWIDE_TOTAL_ABS_THRESHOLD:
            continue

        report = report_by_file[str(curr["file"])]
        issues = report["issues"]
        issues.append(
            {
                "severity": "critical",
                "code": "statewide_total_discontinuity",
                "message": (
                    f"Statewide county-summed TOTAL changed by {pct_change * 100:.2f}% "
                    f"({curr_total:,.0f} vs {prev_total:,.0f}) from previous month; likely parsing error."
                ),
            }
        )
        rebuilt = [Issue(i["severity"], i["code"], i["message"]) for i in issues]
        report["parser_quality_score"] = compute_score(rebuilt)


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(
        p for p in PARSED_DIR.glob("*.csv") if p.name.lower() != "parse_failures.csv"
    )

    reports: list[dict[str, object]] = []
    for csv_path in csv_files:
        report = validate_file(csv_path)
        reports.append(report)

    add_statewide_continuity_checks(reports)

    for csv_path in csv_files:
        report = next(r for r in reports if r["file"] == csv_path.name)
        out_file = REPORT_DIR / f"{csv_path.stem}_validation.json"
        writable = {k: v for k, v in report.items() if not k.startswith("_")}
        out_file.write_text(json.dumps(writable, indent=2), encoding="utf-8")

    summary_rows = []
    for report in reports:
        report = {k: v for k, v in report.items() if not k.startswith("_")}
        issue_counts = {"critical": 0, "warning": 0, "informational": 0}
        for issue in report["issues"]:
            sev = str(issue["severity"])
            if sev in issue_counts:
                issue_counts[sev] += 1
        summary_rows.append(
            {
                "file": report["file"],
                "row_count": report["row_count"],
                "parser_quality_score": report["parser_quality_score"],
                "critical_issues": issue_counts["critical"],
                "warning_issues": issue_counts["warning"],
                "informational_issues": issue_counts["informational"],
            }
        )

    summary_df = pd.DataFrame(summary_rows).sort_values(by=["parser_quality_score", "file"], ascending=[True, True])
    summary_df.to_csv(REPORT_DIR / "validation_summary.csv", index=False)

    aggregate = {
        "files_validated": len(reports),
        "average_parser_quality_score": float(summary_df["parser_quality_score"].mean()) if not summary_df.empty else 0.0,
        "min_parser_quality_score": int(summary_df["parser_quality_score"].min()) if not summary_df.empty else 0,
        "max_parser_quality_score": int(summary_df["parser_quality_score"].max()) if not summary_df.empty else 0,
    }
    (REPORT_DIR / "validation_aggregate.json").write_text(json.dumps(aggregate, indent=2), encoding="utf-8")

    print(json.dumps(aggregate, indent=2))


if __name__ == "__main__":
    main()
