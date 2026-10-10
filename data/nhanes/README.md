Put NHANES SAS transport files here (e.g. `P_DEMO.xpt`, `P_FERTIN.xpt`, `DEMO_J.xpt`), named exactly as on the
CDC website. Q2E looks here first, then in `data/cache/`, then downloads from wwwn.cdc.gov if `Q2E_ALLOW_DOWNLOAD=true`.

Verify the curated dictionary against your files and export every variable label:

    Rscript scripts/verify_nhanes_dictionary.R data/nhanes nhanes_full_dictionary.csv
