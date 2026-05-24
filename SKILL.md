# Maryland Voter Dashboard Skill

## Purpose
Use this skill when working on the Maryland voter registration pipeline and dashboard in this repository. It encodes project-specific rules, expected outputs, and safe modification patterns.

## Scope
This project has four automated steps plus a Streamlit UI:
1. Parse PDF reports into normalized monthly CSVs.
2. Validate parsed outputs and compute quality scores.
3. Detect anomalies across months/counties.
4. Generate improvement suggestions and regression tests.
5. Visualize statewide and county trends in the dashboard.

## Repository Map
- `step1_parser.py`: PDF extraction + OCR fallback + TOTAL reconciliation.
- `step2_validate.py`: schema/quality checks + statewide continuity checks.
- `step3_anomaly.py`: month-over-month and z-score anomaly detection.
- `step4_self_improve.py`: suggestion generation + regression test templates.
- `run_agent_loop.py`: runs steps 1-4 sequentially and writes run summaries.
- `app.py`: Streamlit dashboard (Overview + County Explorer).
- `data/raw/`: source PDFs.
- `data/parsed/`: per-month parsed CSVs and parser logs.
- `data/validation_reports/`: per-file and aggregate validation reports.
- `data/anomaly_reports/`: anomaly findings and summary.
- `agent_suggestions/`: step-4 suggestions and score projections.
- `tests/regression/`: generated regression tests.

## Canonical Output Schema
Parsed monthly CSVs are expected to contain:
- `report_date`
- `county`
- `DEM`, `REP`, `UNA`, `LIB`, `GRN`, `WCP`, `NLM`, `OTH`, `TOTAL`
- `source_pdf`
- `parser_version`

Canonical unaffiliated column is `UNA`.
Compatibility rule: if `UNAF` appears in older files, normalize it to `UNA` at load time.

## Critical Data Rules
- Keep `UNA` as the canonical unaffiliated label across parser, validator, anomaly, tests, and app.
- Do not silently accept major `TOTAL` inconsistencies:
  - Parser may replace row-level `TOTAL` with sum of party columns when mismatch is clearly invalid.
- Validation must preserve county coverage checks for Maryland counties.
- Validation should continue to run cross-month statewide continuity checks.
- Never remove `source_pdf` and `parser_version`; they are required for traceability.

## Dashboard Rules
- `app.py` supports two pages: Overview and County Explorer.
- Sidebar includes `Only display DEM/REP/UNA` flag, default `True`.
- Party-specific charts/tables should honor the visible-party filter.
- Preserve compatibility normalization for legacy `UNAF` columns when loading data.

## Runbook
Use these commands from repository root:

```powershell
python run_agent_loop.py
```
Runs Step 1-4 and writes timestamped summary files in `agent_runs/`.

```powershell
python step1_parser.py
python step2_validate.py
python step3_anomaly.py
python step4_self_improve.py
```
Runs each step individually for focused debugging.

```powershell
streamlit run app.py
```
Starts the dashboard.

## Expected Artifacts After Successful Loop
- Parsed monthly CSVs in `data/parsed/`.
- Validation JSON/CSV summaries in `data/validation_reports/`.
- Anomaly CSV/JSON in `data/anomaly_reports/`.
- Suggestions and scoring artifacts in `agent_suggestions/`.
- Regression tests and manifest in `tests/regression/`.
- Run summary in `agent_runs/latest.json` and timestamped run folder.

## Safe Change Patterns
- For parser changes:
  - Run parser, then validator, then anomaly, then full loop.
  - Confirm schema remains stable and all required columns exist.
- For validator/anomaly thresholds:
  - Re-check false positives and false negatives on latest months.
- For dashboard changes:
  - Verify both pages and all party-dependent visuals.
  - Ensure no KeyError when loading mixed old/new parsed files.

## Troubleshooting Notes
- If table extraction fails for a PDF, parser should attempt OCR fallback.
- If app throws `KeyError: 'UNA'`, check normalization path for legacy `UNAF` data.
- If one month has implausible statewide shift, inspect validator continuity issue and parser logs.
- If totals appear wrong, compare `TOTAL` versus sum of party columns at county level.

## Definition Of Done For Changes
- Code compiles/runs without new runtime errors.
- Full loop (`run_agent_loop.py`) completes successfully.
- Validation aggregate does not regress unexpectedly.
- Dashboard loads and key views render with expected filters.
- New behavior is documented when user-facing.
