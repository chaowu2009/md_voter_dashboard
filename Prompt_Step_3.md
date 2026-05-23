# Step 3 — Add Anomaly and Surge Detection

## Goal
Use historical data to find likely parsing errors or real registration changes.

```text
You are a senior data scientist.

Build anomaly and surge detection for Maryland voter registration parsed CSV files.

Requirements:
1. Use the Step 1 wide schema (report_date, county, DEM, REP, UNA, LIB, GRN, WCP, NLM, OTH, TOTAL, source_pdf, parser_version) as input.
2. Compare each county-party column value (DEM, REP, UNA, LIB, GRN, WCP, NLM, OTH) against previous reports.
3. Compare county TOTAL against previous county TOTAL values.
4. Calculate month-over-month percent change.
5. Calculate z-score where enough history exists.
6. Flag unusual changes.
7. Separate likely parsing errors from possible real voter registration changes.
8. Use simple explainable thresholds first:
   - county total change above 5%
   - county-party change above 10%
   - small-party change above 25%
   - z-score above 3
9. Save anomaly reports to data/anomaly_reports/.
10. Include source_pdf and report_date in every finding.

Do not build a website.
Focus on parser evaluation and data quality.
```
