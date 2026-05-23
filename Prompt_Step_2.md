# Step 2 — Add Validation and Scoring

## Goal
Judge whether the parser result is trustworthy.

```text
You are a senior data quality engineer.

Add validation checks for the parsed Maryland voter registration CSV files.

Requirements:
1. Validate against the Step 1 wide schema:
   - report_date, county, DEM, REP, UNA, LIB, GRN, WCP, NLM, OTH, TOTAL, source_pdf, parser_version
2. Check that all party-count fields (DEM, REP, UNA, LIB, GRN, WCP, NLM, OTH, TOTAL) are valid numbers when present.
3. Treat missing party-count values as allowed null values when the source PDF does not contain that party column.
4. Check that expected Maryland counties are present.
5. Check that known party codes are present when available.
6. Check key uniqueness for wide rows using:
   - report_date + county
7. Produce a parser_quality_score from 0 to 100.
8. Save validation reports to data/validation_reports/.
9. Clearly label issues as:
   - critical
   - warning
   - informational

Do not build a website.
Keep the design simple and testable.
```
