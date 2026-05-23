from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

PARSED_DIR = Path("data/parsed")
OUT_DIR = Path("data/anomaly_reports")

PARTY_COLUMNS = ["DEM", "REP", "UNA", "LIB", "GRN", "WCP", "NLM", "OTH"]
VALUE_COLUMNS = [*PARTY_COLUMNS, "TOTAL"]
SMALL_PARTY_COLUMNS = {"LIB", "GRN", "WCP", "NLM", "OTH"}
MIN_HISTORY_FOR_ZSCORE = 6
MIN_BASELINE_TOTAL = 50000
MIN_ABS_DELTA_TOTAL = 3000
MIN_BASELINE_PARTY = 1000
MIN_ABS_DELTA_PARTY = 250
MIN_BASELINE_SMALL_PARTY = 200
MIN_ABS_DELTA_SMALL_PARTY = 75


def normalize_party_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "UNA" not in df.columns and "UNAF" in df.columns:
        df = df.rename(columns={"UNAF": "UNA"})
    return df


def load_data() -> pd.DataFrame:
    files = sorted(PARSED_DIR.glob("MSR-*.csv"))
    if not files:
        raise FileNotFoundError("No parsed CSV files found in data/parsed")

    frames = []
    for path in files:
        df = pd.read_csv(path)
        df = normalize_party_columns(df)
        df["source_csv"] = path.name
        frames.append(df)

    data = pd.concat(frames, ignore_index=True)
    data["report_date"] = pd.to_datetime(data["report_date"], errors="coerce")
    data = data.dropna(subset=["report_date", "county"]).copy()
    for col in VALUE_COLUMNS:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    return data


def classify_finding(metric: str, flags: list[str], pct_change: float | None, z_score: float | None, abs_delta: float) -> str:
    # Heuristic classification: require stronger evidence before calling parser error.
    if metric == "TOTAL" and (pct_change is not None and abs(pct_change) > 0.15) and abs_delta >= MIN_ABS_DELTA_TOTAL:
        return "likely_parsing_error"
    if "zscore_gt_3" in flags and z_score is not None and abs(z_score) >= 4.5 and abs_delta >= MIN_ABS_DELTA_PARTY:
        return "likely_parsing_error"
    if pct_change is not None and abs(pct_change) >= 0.6 and abs_delta >= MIN_ABS_DELTA_PARTY:
        return "likely_parsing_error"
    return "possible_real_change"


def detect_anomalies(data: pd.DataFrame) -> pd.DataFrame:
    findings: list[dict[str, object]] = []

    grouped = data.sort_values(["county", "report_date"]).groupby("county", sort=False)

    for county, county_df in grouped:
        county_df = county_df.reset_index(drop=True)

        for idx in range(1, len(county_df)):
            current = county_df.iloc[idx]
            previous = county_df.iloc[idx - 1]

            for metric in VALUE_COLUMNS:
                cur_val = current.get(metric)
                prev_val = previous.get(metric)

                if pd.isna(cur_val) or pd.isna(prev_val):
                    continue

                prev_val_f = float(prev_val)
                cur_val_f = float(cur_val)
                if prev_val_f == 0:
                    continue

                pct_change = (cur_val_f - prev_val_f) / prev_val_f
                abs_pct = abs(pct_change)
                abs_delta = abs(cur_val_f - prev_val_f)

                history_series = county_df.loc[: idx - 1, metric].dropna().astype(float)
                z_score = None
                if len(history_series) >= MIN_HISTORY_FOR_ZSCORE:
                    std = float(history_series.std(ddof=0))
                    if std > 0:
                        z_score = (cur_val_f - float(history_series.mean())) / std

                flags: list[str] = []

                if metric == "TOTAL" and abs_pct > 0.05 and prev_val_f >= MIN_BASELINE_TOTAL and abs_delta >= MIN_ABS_DELTA_TOTAL:
                    flags.append("county_total_change_gt_5pct")
                if metric in PARTY_COLUMNS and abs_pct > 0.10 and prev_val_f >= MIN_BASELINE_PARTY and abs_delta >= MIN_ABS_DELTA_PARTY:
                    flags.append("county_party_change_gt_10pct")
                if metric in SMALL_PARTY_COLUMNS and abs_pct > 0.25 and prev_val_f >= MIN_BASELINE_SMALL_PARTY and abs_delta >= MIN_ABS_DELTA_SMALL_PARTY:
                    flags.append("small_party_change_gt_25pct")
                if z_score is not None and abs(z_score) > 3:
                    flags.append("zscore_gt_3")

                if not flags:
                    continue

                classification = classify_finding(metric, flags, pct_change, z_score, abs_delta)
                findings.append(
                    {
                        "report_date": current["report_date"].date().isoformat(),
                        "county": county,
                        "metric": metric,
                        "current_value": int(cur_val_f),
                        "previous_value": int(prev_val_f),
                        "abs_delta": int(abs_delta),
                        "mom_percent_change": round(pct_change * 100.0, 3),
                        "z_score": None if z_score is None else round(float(z_score), 3),
                        "flags": ";".join(flags),
                        "classification": classification,
                        "source_pdf": str(current.get("source_pdf", "")),
                    }
                )

    return pd.DataFrame(findings)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    data = load_data()
    anomalies = detect_anomalies(data)

    if anomalies.empty:
        anomalies = pd.DataFrame(
            columns=[
                "report_date",
                "county",
                "metric",
                "current_value",
                "previous_value",
                "abs_delta",
                "mom_percent_change",
                "z_score",
                "flags",
                "classification",
                "source_pdf",
            ]
        )

    anomalies = anomalies.sort_values(["report_date", "county", "metric"], ascending=[True, True, True])
    anomalies.to_csv(OUT_DIR / "anomaly_findings.csv", index=False)

    summary = {
        "total_findings": int(len(anomalies)),
        "likely_parsing_error": int((anomalies["classification"] == "likely_parsing_error").sum()) if not anomalies.empty else 0,
        "possible_real_change": int((anomalies["classification"] == "possible_real_change").sum()) if not anomalies.empty else 0,
        "distinct_report_dates": int(anomalies["report_date"].nunique()) if not anomalies.empty else 0,
        "distinct_counties": int(anomalies["county"].nunique()) if not anomalies.empty else 0,
    }

    (OUT_DIR / "anomaly_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
