from pathlib import Path
import pandas as pd

REQUIRED = [
    "report_date", "county", "DEM", "REP", "UNA", "LIB", "GRN", "WCP",
    "NLM", "OTH", "TOTAL", "source_pdf", "parser_version"
]


def test_required_columns_exist_in_parsed_outputs():
    for path in sorted(Path("data/parsed").glob("MSR-*.csv")):
        df = pd.read_csv(path)
        missing = [c for c in REQUIRED if c not in df.columns]
        assert not missing, f"{path.name} missing columns: {missing}"
