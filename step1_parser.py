from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pdfplumber
from rapidocr_onnxruntime import RapidOCR

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/parsed")
PARSER_VERSION = "1.3.1"
EXCLUDED_FILES = {"MSR-2025.pdf"}

SCHEMA_PARTIES = [
    "DEM",
    "REP",
    "UNA",
    "LIB",
    "GRN",
    "WCP",
    "NLM",
    "OTH",
    "TOTAL",
]

PARTY_ALIASES = {
    "DEM": "DEM",
    "DEMOCRATIC": "DEM",
    "REP": "REP",
    "REPUBLICAN": "REP",
    "UNAF": "UNA",
    "UNA": "UNA",
    "UNF": "UNA",
    "UNAFFILIATED": "UNA",
    "LIB": "LIB",
    "LIBERTARIAN": "LIB",
    "GRN": "GRN",
    "GREEN": "GRN",
    "WCP": "WCP",
    "WORKINGCLASS": "WCP",
    "WORKING": "WCP",
    "NLM": "NLM",
    "NOLABELS": "NLM",
    "OTH": "OTH",
    "OTHER": "OTH",
    "TOTAL": "TOTAL",
}

EXPECTED_COUNTIES = [
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
]

OCR_PARTY_ORDER = ["DEM", "REP", "NLM", "LIB", "UNA", "OTH", "TOTAL"]

ROW_TOTAL_REPLACE_ABS_THRESHOLD = 500
ROW_TOTAL_REPLACE_PCT_THRESHOLD = 0.01


def normalize_party_name(value: str | None) -> str | None:
    if not value:
        return None
    key = re.sub(r"[^A-Z]", "", value.upper())
    return PARTY_ALIASES.get(key)


def parse_report_date(pdf_path: Path) -> str:
    match = re.search(r"(\d{4})_(\d{2})", pdf_path.stem)
    if not match:
        return ""
    year, month = match.groups()
    return datetime(int(year), int(month), 1).date().isoformat()


def clean_int(value: str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return None


def standardize_county_name(value: str) -> str:
    text = value.strip().upper()
    text = text.replace("PRINCE GEORGE'S", "PR. GEORGE'S")
    text = text.replace("SAINT MARY'S", "ST. MARY'S")
    return text


def extract_rows_from_table(table: list[list[str | None]], pdf_path: Path) -> pd.DataFrame:
    active_headers, active_start, active_end = extract_active_headers(table)
    report_date = parse_report_date(pdf_path)
    rows: list[dict[str, object]] = []

    for raw_row in table[2:]:
        if not raw_row:
            continue
        county = str(raw_row[0] or "").strip()
        if not county:
            continue
        if county.upper() == "TOTAL":
            continue

        row: dict[str, object] = {
            "report_date": report_date,
            "county": county,
            "source_pdf": pdf_path.name,
            "parser_version": PARSER_VERSION,
        }
        for party in SCHEMA_PARTIES:
            row[party] = None

        for offset, party in enumerate(active_headers):
            if not party:
                continue
            idx = active_start + offset
            value = clean_int(raw_row[idx] if idx < len(raw_row) else None)
            if party == "WKG":
                row["WCP"] = (row.get("WCP") or 0) + (value or 0)
            elif party == "CON" or party == "IND":
                row["OTH"] = (row.get("OTH") or 0) + (value or 0)
            elif party in row:
                row[party] = value

        rows.append(row)

    if not rows:
        raise ValueError("No county rows parsed")

    return pd.DataFrame(rows)


def ocr_group_lines(ocr_results: list[list[object]], y_threshold: float = 14.0) -> list[str]:
    entries: list[tuple[float, float, str]] = []
    for item in ocr_results:
        box = item[0]
        text = str(item[1]).strip()
        if not text:
            continue

        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        entries.append((cy, cx, text))

    entries.sort(key=lambda x: (x[0], x[1]))

    grouped: list[list[tuple[float, str]]] = []
    centers: list[float] = []
    for cy, cx, text in entries:
        if not grouped:
            grouped.append([(cx, text)])
            centers.append(cy)
            continue
        if abs(cy - centers[-1]) <= y_threshold:
            grouped[-1].append((cx, text))
            centers[-1] = (centers[-1] + cy) / 2
        else:
            grouped.append([(cx, text)])
            centers.append(cy)

    lines: list[str] = []
    for line_parts in grouped:
        parts = [t for _, t in sorted(line_parts, key=lambda x: x[0])]
        line = " ".join(parts)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines


def parse_ocr_county_line(line: str) -> tuple[str, dict[str, int | None]] | None:
    upper_line = standardize_county_name(line)
    county = None
    for candidate in EXPECTED_COUNTIES:
        if upper_line.startswith(candidate):
            county = candidate
            break
    if not county:
        return None

    numbers = re.findall(r"\d[\d,]*", line)
    if len(numbers) < 9:
        return None

    # For this report family, active block is the 7 values before trailing CONF/INACTIVE.
    active_block = numbers[-9:-2]
    if len(active_block) != 7:
        return None

    values: dict[str, int | None] = {k: None for k in SCHEMA_PARTIES}
    for key, raw in zip(OCR_PARTY_ORDER, active_block):
        if key in values:
            values[key] = clean_int(raw)

    return county, values


def parse_pdf_with_ocr(pdf_path: Path) -> pd.DataFrame:
    ocr_engine = RapidOCR()
    report_date = parse_report_date(pdf_path)
    rows: dict[str, dict[str, object]] = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            img = page.to_image(resolution=280).original
            ocr_results, _ = ocr_engine(np.array(img))
            if not ocr_results:
                continue

            lines = ocr_group_lines(ocr_results)
            for line in lines:
                parsed = parse_ocr_county_line(line)
                if not parsed:
                    continue
                county, values = parsed
                if county in rows:
                    continue

                row: dict[str, object] = {
                    "report_date": report_date,
                    "county": county,
                    "source_pdf": pdf_path.name,
                    "parser_version": PARSER_VERSION,
                }
                row.update(values)
                rows[county] = row

    if len(rows) < 20:
        raise ValueError("OCR fallback could not recover enough county rows")

    return pd.DataFrame(list(rows.values()))


def extract_active_headers(table: list[list[str | None]]) -> tuple[list[str], int, int]:
    if len(table) < 2:
        raise ValueError("Table is missing header rows")

    header_row = table[1]
    total_positions = [i for i, val in enumerate(header_row) if str(val or "").strip().upper() == "TOTAL"]
    if len(total_positions) < 2:
        raise ValueError("Could not locate both TOTAL columns in header")

    start = total_positions[0] + 1
    end = total_positions[1]

    raw_headers = [str(header_row[i] or "").strip() for i in range(start, end + 1)]
    normalized = [normalize_party_name(h) or "" for h in raw_headers]
    if not normalized or normalized[-1] != "TOTAL":
        raise ValueError("Could not identify TOTAL ACTIVE REGISTRATION block")

    return normalized, start, end


def is_county_active_table(table: list[list[str | None]]) -> bool:
    if len(table) < 2:
        return False
    first_row = [str(c or "").strip().upper() for c in table[0]]
    second_row = [str(c or "").strip().upper() for c in table[1]]
    has_active_table_title = any("TOTAL ACTIVE REGISTRATION" in cell for cell in first_row)
    total_count = sum(1 for c in second_row if c == "TOTAL")
    return has_active_table_title and total_count >= 2


def find_county_active_table(pdf: pdfplumber.PDF) -> list[list[str | None]]:
    for page in pdf.pages:
        for table in page.extract_tables() or []:
            if is_county_active_table(table):
                return table
    raise ValueError("Could not find county TOTAL ACTIVE REGISTRATION table")


def parse_pdf(pdf_path: Path) -> pd.DataFrame:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                raise ValueError("PDF has no pages")
            table = find_county_active_table(pdf)
            return extract_rows_from_table(table, pdf_path)
    except Exception as native_exc:  # noqa: BLE001
        logging.warning("Primary parse failed for %s, trying OCR fallback: %s", pdf_path.name, native_exc)
        try:
            return parse_pdf_with_ocr(pdf_path)
        except Exception as ocr_exc:  # noqa: BLE001
            raise ValueError(f"Primary parse and OCR fallback failed: {ocr_exc}") from native_exc


def reconcile_row_totals(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Replace clearly inconsistent TOTAL values with sum of party columns."""
    party_cols = [c for c in SCHEMA_PARTIES if c != "TOTAL"]

    for col in [*party_cols, "TOTAL"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    party_sum = df[party_cols].fillna(0).sum(axis=1)
    total_col = df["TOTAL"]

    total_missing = total_col.isna()
    abs_diff = (total_col - party_sum).abs()
    rel_diff = abs_diff / total_col.abs().replace(0, np.nan)

    inconsistent = (~total_missing) & (
        (abs_diff >= ROW_TOTAL_REPLACE_ABS_THRESHOLD)
        & (rel_diff >= ROW_TOTAL_REPLACE_PCT_THRESHOLD)
    )
    replace_mask = total_missing | inconsistent

    replacements = int(replace_mask.sum())
    if replacements > 0:
        df.loc[replace_mask, "TOTAL"] = party_sum.loc[replace_mask].astype("int64")

    return df, replacements


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_file = OUT_DIR / "parse_failures.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode="w", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    pdf_files = sorted(p for p in RAW_DIR.glob("*.pdf") if p.name not in EXCLUDED_FILES)
    if not pdf_files:
        logging.warning("No PDF files found in %s", RAW_DIR)
        return

    success = 0
    failed = 0

    for pdf_path in pdf_files:
        out_path = OUT_DIR / f"{pdf_path.stem}.csv"
        if out_path.exists():
            out_path.unlink()
        try:
            df = parse_pdf(pdf_path)
            df, replacements = reconcile_row_totals(df)
            ordered_cols = ["report_date", "county", *SCHEMA_PARTIES, "source_pdf", "parser_version"]
            df = df[ordered_cols]
            df.to_csv(out_path, index=False)
            success += 1
            if replacements > 0:
                logging.warning(
                    "Replaced TOTAL using party sum for %s: %d row(s)",
                    pdf_path.name,
                    replacements,
                )
            logging.info("Parsed %s -> %s (%d rows)", pdf_path.name, out_path.name, len(df))
        except Exception as exc:  # noqa: BLE001
            if out_path.exists():
                out_path.unlink()
            failed += 1
            logging.exception("Failed to parse %s: %s", pdf_path.name, exc)

    logging.info("Done. Success=%d Failed=%d", success, failed)


if __name__ == "__main__":
    main()
