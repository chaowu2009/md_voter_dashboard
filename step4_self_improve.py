from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

VALIDATION_DIR = Path("data/validation_reports")
ANOMALY_DIR = Path("data/anomaly_reports")
SUGGESTIONS_DIR = Path("agent_suggestions")
REGRESSION_DIR = Path("tests/regression")
PARSE_FAILURE_LOG = Path("data/parsed/parse_failures.log")


def load_validation_reports() -> tuple[list[dict], dict]:
    reports = []
    for p in sorted(VALIDATION_DIR.glob("*_validation.json")):
        reports.append(json.loads(p.read_text(encoding="utf-8")))

    aggregate_path = VALIDATION_DIR / "validation_aggregate.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8")) if aggregate_path.exists() else {}
    return reports, aggregate


def load_parse_failures() -> list[str]:
    if not PARSE_FAILURE_LOG.exists():
        return []
    lines = [ln.strip() for ln in PARSE_FAILURE_LOG.read_text(encoding="utf-8").splitlines() if "ERROR Failed to parse" in ln]
    return lines


def infer_failure_modes(validation_reports: list[dict], anomaly_df: pd.DataFrame, parse_failures: list[str]) -> dict[str, dict]:
    modes: dict[str, dict] = defaultdict(lambda: {"count": 0, "evidence": []})
    validation_parser_signal_count = 0

    # Validation-derived modes
    for report in validation_reports:
        file_name = report.get("file", "")
        for issue in report.get("issues", []):
            code = str(issue.get("code", ""))
            msg = str(issue.get("message", ""))
            sev = str(issue.get("severity", "informational"))

            if code in {"missing_required_columns", "missing_known_party_columns"}:
                key = "missing_columns"
            elif code == "duplicate_keys":
                key = "duplicate_keys"
            elif code == "invalid_numeric_field":
                key = "numeric_parsing_errors"
            elif code in {"missing_expected_counties", "unexpected_counties"}:
                key = "missed_county_rows"
            else:
                key = "other_validation_issue"

            modes[key]["count"] += 1
            modes[key]["evidence"].append(
                {
                    "source": file_name,
                    "severity": sev,
                    "detail": msg,
                }
            )

            if sev in {"critical", "warning"} and key != "other_validation_issue":
                validation_parser_signal_count += 1

    if parse_failures:
        modes["parse_extraction_failure"]["count"] += len(parse_failures)
        modes["parse_extraction_failure"]["evidence"] = [
            {"source": "parse_failures.log", "severity": "critical", "detail": ln} for ln in parse_failures[:5]
        ]

    parser_fault_corroborated_by_validation = validation_parser_signal_count > 0

    if not anomaly_df.empty:
        # Heuristic failure mode mapping from anomaly flags.
        for _, row in anomaly_df.iterrows():
            flags = str(row.get("flags", ""))
            classification = str(row.get("classification", ""))
            metric = str(row.get("metric", ""))
            source_pdf = str(row.get("source_pdf", ""))

            if classification == "likely_parsing_error":
                if parser_fault_corroborated_by_validation:
                    if "zscore_gt_3" in flags or "county_party_change_gt_10pct" in flags:
                        mode_key = "wrong_header_mapping"
                    elif metric == "TOTAL" and "county_total_change_gt_5pct" in flags:
                        mode_key = "missed_county_rows"
                    else:
                        mode_key = "column_order_change"
                else:
                    mode_key = "anomaly_only_drift"

                modes[mode_key]["count"] += 1
                modes[mode_key]["evidence"].append(
                    {
                        "source": source_pdf,
                        "severity": "warning",
                        "detail": f"metric={metric}, flags={flags}",
                    }
                )

    return dict(modes)


def make_suggestions(modes: dict[str, dict]) -> list[dict]:
    suggestions: list[dict] = []

    parser_fault_modes = {"missing_columns", "duplicate_keys", "numeric_parsing_errors", "missed_county_rows", "parse_extraction_failure", "wrong_header_mapping", "column_order_change"}
    has_parser_fault_signal = any(mode in modes for mode in parser_fault_modes)

    if "parse_extraction_failure" in modes:
        suggestions.append(
            {
                "id": "SUG-004",
                "title": "Add OCR fallback for unreadable PDFs",
                "root_cause_categories": ["numeric parsing errors", "parse extraction failure"],
                "parser_changes": [
                    "Keep pdfplumber as primary extractor and trigger OCR only when table/header confidence fails.",
                    "Run OCR fallback on failed files and re-parse county table from OCR text/table output.",
                    "Tag extraction method in parser logs and keep hard numeric validation after OCR.",
                ],
                "risk": "medium",
                "expected_score_impact": "+3 to +8 points on currently failed files",
            }
        )

    if "wrong_header_mapping" in modes or "column_order_change" in modes:
        suggestions.append(
            {
                "id": "SUG-001",
                "title": "Strengthen header-to-schema mapping",
                "root_cause_categories": ["wrong header mapping", "column order change"],
                "parser_changes": [
                    "Detect county table by semantic cues, not fixed row index.",
                    "Map party columns using canonical alias dictionary and confidence score.",
                    "If header confidence < threshold, fail file with explicit parse_error code.",
                ],
                "risk": "low",
                "expected_score_impact": "+2 to +5 points on files with parse artifacts",
            }
        )

    if "missed_county_rows" in modes:
        suggestions.append(
            {
                "id": "SUG-002",
                "title": "Add county row completeness checks in parser",
                "root_cause_categories": ["missed county rows"],
                "parser_changes": [
                    "Assert 24 Maryland jurisdictions exist before writing CSV.",
                    "If fewer than 24 rows, trigger fallback parse strategy or fail fast.",
                    "Emit structured parse diagnostics with missing county list.",
                ],
                "risk": "low",
                "expected_score_impact": "+1 to +3 points by reducing silent truncation",
            }
        )

    if "numeric_parsing_errors" in modes:
        suggestions.append(
            {
                "id": "SUG-003",
                "title": "Harden numeric normalization",
                "root_cause_categories": ["numeric parsing errors"],
                "parser_changes": [
                    "Normalize commas/spaces/currency-like OCR artifacts before int cast.",
                    "Reject malformed numeric tokens with row-level errors.",
                ],
                "risk": "low",
                "expected_score_impact": "+1 to +2 points",
            }
        )

    if "anomaly_only_drift" in modes and not has_parser_fault_signal:
        suggestions.append(
            {
                "id": "SUG-010",
                "title": "Abstain parser changes and monitor drift",
                "root_cause_categories": ["possible real-world registration shifts"],
                "parser_changes": [
                    "Do not change parser solely based on anomaly spikes without validation evidence.",
                    "Track repeated anomalies for 3 consecutive periods before proposing parser edits.",
                ],
                "risk": "none",
                "expected_score_impact": "0 (reduces false-positive change proposals)",
            }
        )

    if not suggestions:
        suggestions.append(
            {
                "id": "SUG-000",
                "title": "No critical parser changes required",
                "root_cause_categories": ["none"],
                "parser_changes": ["Current parser quality is stable; keep monitoring anomaly drift."],
                "risk": "none",
                "expected_score_impact": "0",
            }
        )

    return suggestions


def write_regression_tests(suggestions: list[dict], modes: dict[str, dict]) -> list[str]:
    REGRESSION_DIR.mkdir(parents=True, exist_ok=True)
    created = []

    tests_by_name = {
        "test_county_row_completeness.py": '''from pathlib import Path\nimport pandas as pd\n\n\ndef test_every_parsed_csv_has_24_counties():\n    parsed_dir = Path("data/parsed")\n    for path in sorted(parsed_dir.glob("MSR-*.csv")):\n        df = pd.read_csv(path)\n        assert df["county"].nunique() == 24, f"{path.name} does not contain 24 counties"\n''',
        "test_required_schema_columns.py": '''from pathlib import Path\nimport pandas as pd\n\nREQUIRED = [\n    "report_date", "county", "DEM", "REP", "UNA", "LIB", "GRN", "WCP",\n    "NLM", "OTH", "TOTAL", "source_pdf", "parser_version"\n]\n\n\ndef test_required_columns_exist_in_parsed_outputs():\n    for path in sorted(Path("data/parsed").glob("MSR-*.csv")):\n        df = pd.read_csv(path)\n        missing = [c for c in REQUIRED if c not in df.columns]\n        assert not missing, f"{path.name} missing columns: {missing}"\n''',
        "test_numeric_fields_castable.py": '''from pathlib import Path\nimport pandas as pd\n\nPARTIES = ["DEM", "REP", "UNA", "LIB", "GRN", "WCP", "NLM", "OTH", "TOTAL"]\n\n\ndef test_party_fields_are_numeric_or_null():\n    for path in sorted(Path("data/parsed").glob("MSR-*.csv")):\n        df = pd.read_csv(path)\n        for col in PARTIES:\n            coerced = pd.to_numeric(df[col], errors="coerce")\n            invalid = df[col].notna() & coerced.isna()\n            assert int(invalid.sum()) == 0, f"{path.name} has invalid numeric values in {col}"\n''',
    }

    required_tests = set()
    mode_keys = set(modes.keys())

    if {"wrong_header_mapping", "column_order_change"} & mode_keys:
        required_tests.add("test_required_schema_columns.py")
    if "missed_county_rows" in mode_keys:
        required_tests.add("test_county_row_completeness.py")
    if "numeric_parsing_errors" in mode_keys:
        required_tests.add("test_numeric_fields_castable.py")

    # Always include baseline schema test.
    required_tests.add("test_required_schema_columns.py")

    for name in sorted(required_tests):
        path = REGRESSION_DIR / name
        path.write_text(tests_by_name[name], encoding="utf-8")
        created.append(path.name)

    manifest = {
        "generated_from_suggestions": [s["id"] for s in suggestions],
        "tests": created,
    }
    (REGRESSION_DIR / "regression_test_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return created


def write_before_after_scoring(validation_aggregate: dict, suggestions: list[dict], modes: dict[str, dict]) -> dict:
    baseline_avg = float(validation_aggregate.get("average_parser_quality_score", 0.0))
    baseline_min = int(validation_aggregate.get("min_parser_quality_score", 0))

    # Conservative estimate from improvement suggestions and observed failure modes.
    mode_weight = min(5.0, sum(v.get("count", 0) for v in modes.values()) / 200.0)
    projected_avg = min(100.0, baseline_avg + 1.0 + mode_weight)
    projected_min = min(100, baseline_min + 1)

    framework = {
        "before": {
            "average_parser_quality_score": baseline_avg,
            "min_parser_quality_score": baseline_min,
        },
        "after_projected": {
            "average_parser_quality_score": round(projected_avg, 2),
            "min_parser_quality_score": projected_min,
        },
        "acceptance_gates": [
            "No new critical issues in validation reports",
            "Average parser_quality_score must not decrease",
            "All generated regression tests must pass before approval",
            "Human reviewer approval required before production deployment",
        ],
        "suggestion_ids": [s["id"] for s in suggestions],
    }

    (SUGGESTIONS_DIR / "before_after_scoring.json").write_text(json.dumps(framework, indent=2), encoding="utf-8")
    return framework


def main() -> None:
    SUGGESTIONS_DIR.mkdir(parents=True, exist_ok=True)

    validation_reports, validation_aggregate = load_validation_reports()
    anomaly_csv = ANOMALY_DIR / "anomaly_findings.csv"
    anomaly_df = pd.read_csv(anomaly_csv) if anomaly_csv.exists() else pd.DataFrame()
    parse_failures = load_parse_failures()

    modes = infer_failure_modes(validation_reports, anomaly_df, parse_failures)
    suggestions = make_suggestions(modes)

    analysis = {
        "failure_modes": {
            key: {
                "count": value["count"],
                "sample_evidence": value["evidence"][:5],
            }
            for key, value in modes.items()
        },
        "suggestions": suggestions,
    }

    (SUGGESTIONS_DIR / "step4_failure_analysis.json").write_text(json.dumps(analysis, indent=2), encoding="utf-8")

    tests_created = write_regression_tests(suggestions, modes)
    scoring = write_before_after_scoring(validation_aggregate, suggestions, modes)

    run_summary = {
        "suggestions_written": len(suggestions),
        "regression_tests_generated": tests_created,
        "failure_modes_detected": list(modes.keys()),
        "before_after_scoring_file": "before_after_scoring.json",
    }
    (SUGGESTIONS_DIR / "step4_run_summary.json").write_text(json.dumps(run_summary, indent=2), encoding="utf-8")

    print(json.dumps({"run_summary": run_summary, "scoring": scoring}, indent=2))


if __name__ == "__main__":
    main()
