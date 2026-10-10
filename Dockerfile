# Q2E - Question to Evidence (R biostatistics engine + Python orchestrator + web UI)
FROM rocker/r-ver:4.4.1

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*
RUN Rscript -e 'install.packages(c("survey","jsonlite","haven","ggplot2","mice","mitools","yaml","testthat"))'

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY . .
RUN Rscript r/synth/make_synthetic_nhanes.R data/synthetic 12000 20261010 && mkdir -p workspace data/nhanes data/cache

ENV Q2E_WORKSPACE=/app/workspace Q2E_NHANES_DIR=/app/data/nhanes
EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "q2e.server:app", "--host", "0.0.0.0", "--port", "8000"]
