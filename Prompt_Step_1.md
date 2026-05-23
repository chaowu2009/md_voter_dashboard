# Step 1 — Build the Basic Parser

## Goal
Convert each Maryland voter registration PDF into one normalized CSV.

```text
You are a senior Python data engineer.

Build a PDF parser for Maryland voter registration PDF files already stored in data/raw/. forgoet MSR-2025.pdf

Requirements:
1. Use pdfplumber first.
2. Only consider "TOTAL ACTIVE REGISTRATION" or "Total registration". Remember the party names may change orders in the pdf files. All columns are [DEM, REP, UNA, LIB, GRN, WCP, NLM, OTH, TOTAL]. Some columns may miss for some months. When the column does not show in the pdf, use "None" value, but keep all the columns for consistency for all data.

Here are some explanation of these.

| Code                      | Party / Affiliation | Notes                                              |
| ------------------------- | ------------------- | ------------------- |
| DEM                       | Democratic Party    | Major party                                        |
| REP                       | Republican Party    | Major party                                        |
| UNA                       | Unaffiliated        | No party affiliation                               |
| LIB                       | Libertarian Party   | Official minor party                               |
| GRN                       | Green Party         | Official minor party                               |
| WCP / Working Class       | Working Class Party | Sometimes appears differently by dataset           |
| NLM                       | No Labels Maryland  | Newer minor party; appeared recently               |
| OTH                       | Other               | Aggregated smaller parties                         |


3. Normalize all outputs into this schema:
   report_date, county, DEM, REP, UNA, LIB, GRN, WCP, NLM, OTH, TOTAL, source_pdf, parser_version
   
   Note: If that party has no number or does not show up in the pdf, set it null. 

4. Handle column order changes by matching column names, not positions. 

5. Save results to data/parsed/.
6. Add clear logging for files that fail to parse.
7. Do not build a website or Streamlit app.

Create clean, minimal Python code with comments.
```
