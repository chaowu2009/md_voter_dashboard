# Self-Evolving Agent Summary Report

## Scope
This report summarizes end-to-end execution of the 4-step agent loop and the self-evolution changes applied to improve consistency and reasonableness.

- Orchestrator: [run_agent_loop.py](run_agent_loop.py)
- Steps:
  - [step1_parser.py](step1_parser.py)
  - [step2_validate.py](step2_validate.py)
  - [step3_anomaly.py](step3_anomaly.py)
  - [step4_self_improve.py](step4_self_improve.py)

## What Was Improved During Self-Evolution

### 1) Step 3 anomaly signal hardening
Updated [step3_anomaly.py](step3_anomaly.py) to reduce false positives:
- Added minimum baselines and absolute delta thresholds before firing percent-change rules.
- Kept z-score checks but required stronger combined evidence for parser-error classification.
- Added `abs_delta` to anomaly output for explainability.

### 2) Step 4 evidence-corroboration logic
Updated [step4_self_improve.py](step4_self_improve.py) to improve decision quality:
- Reads parse failures from [data/parsed/parse_failures.log](data/parsed/parse_failures.log).
- Separates parser-fault evidence from anomaly-only drift.
- Requires validation corroboration before mapping anomaly spikes to parser-structure failures.
- Produces focused suggestion for OCR fallback when extraction failures are observed.

## Run Comparison

### Baseline (before evolution)
- Run: [agent_runs/20260523T035359Z/run_summary.json](agent_runs/20260523T035359Z/run_summary.json)
- Results:
  - `anomaly.total_findings`: 473
  - `anomaly.likely_parsing_error`: 189
  - `step4.failure_modes_detected`: other_validation_issue, wrong_header_mapping
  - `step4.suggestions_written`: 1

### Post-evolution run 1
- Run: [agent_runs/20260523T035606Z/run_summary.json](agent_runs/20260523T035606Z/run_summary.json)
- Results:
  - `anomaly.total_findings`: 260
  - `anomaly.likely_parsing_error`: 36
  - `step4.failure_modes_detected`: other_validation_issue, parse_extraction_failure, anomaly_only_drift
  - `step4.suggestions_written`: 1

### Post-evolution run 2 (stability check)
- Run: [agent_runs/20260523T035638Z/run_summary.json](agent_runs/20260523T035638Z/run_summary.json)
- Results (identical to run 1):
  - `anomaly.total_findings`: 260
  - `anomaly.likely_parsing_error`: 36
  - `step4.failure_modes_detected`: other_validation_issue, parse_extraction_failure, anomaly_only_drift
  - `step4.suggestions_written`: 1

## Consistency Assessment
The system appears consistent across two consecutive post-evolution runs:
- Same step statuses (`success` for Step 1 through Step 4)
- Same key metrics in anomaly and suggestion outputs
- Same failure-mode pattern and recommendation

Latest stable summary:
- [agent_runs/latest.json](agent_runs/latest.json)

## Reasonableness Assessment
Current outcomes are more reasonable than baseline:
- Significant reduction in anomaly volume and parser-error labeling
- Step 4 now avoids over-attributing anomaly spikes to parser defects
- Step 4 recommendation is focused on observed hard failures (OCR fallback for unreadable PDFs)

Primary unresolved issue remains parse coverage:
- Failed PDFs (from Step 1 log):
  - MSR-2025_04.pdf
  - MSR-2025_12.pdf
  - MSR-2026_01.pdf
- Evidence source: [data/parsed/parse_failures.log](data/parsed/parse_failures.log)

## Recommended Next Action
Implement OCR fallback in [step1_parser.py](step1_parser.py) for files that fail table/header confidence checks, then rerun the loop and validate:
- Increased parsed CSV coverage
- Reduction of `parse_extraction_failure` in Step 4
- Stable or improved validation score profile
