# Step 4 — Add Agentic Self-Improvement Loop

## Goal
Let AI diagnose failures and suggest parser improvements.

```text
You are an agentic AI software engineer.

Create a human-in-the-loop self-improvement workflow for the Maryland voter registration PDF parser.

Requirements:
1. Assume parser outputs follow the Step 1 wide schema:
   - report_date, county, DEM, REP, UNA, LIB, GRN, WCP, NLM, OTH, TOTAL, source_pdf, parser_version
2. Read validation reports and anomaly reports generated from that schema.
3. Identify whether failures are likely caused by:
   - missing required fields
   - duplicate keys (report_date + county)
   - missing columns
   - column order change
   - wrong header mapping
   - missed county rows
   - party code mismatch
   - numeric parsing errors
4. Suggest specific parser improvements.
5. Generate regression tests for each failure.
6. Do not automatically deploy code changes.
7. Save proposed fixes to agent_suggestions/.
8. Save generated tests to tests/regression/.
9. Include a before/after scoring framework so parser changes can be evaluated.

Important rule:
The agent may propose code changes, but a human must approve them before production use.

Keep the implementation minimal and practical.
```
