`tables.csv` (NHANES table names and descriptions, 1999-2023) is derived from
`inst/extdata/audit_all_nhanes_tables.csv` in the **nhanesdata** R package (MIT License, (c) 2025 nhanesdata authors),
https://github.com/kylegrealis/nhanesdata. Table names and descriptions originate from the CDC/NCHS NHANES website (public domain).

`catalog.csv` (13,152 variables, all cycles 1999-2023) was built with `scripts/build_nhanes_catalog.py --cdc` from the
official CDC/NCHS "Questionnaires, Datasets, and Related Documentation" variable lists
(https://wwwn.cdc.gov/nchs/nhanes/search/default.aspx; Demographics, Dietary, Examination, Laboratory, Questionnaire;
public domain). Rows are uncurated: any mapping that uses them must be checked against the CDC codebook.
