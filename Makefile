.PHONY: install synth serve test demo docker
install:
	pip install -r requirements-dev.txt
	Rscript r/install_packages.R
synth:
	Rscript r/synth/make_synthetic_nhanes.R data/synthetic 12000 20261010
serve:
	python -m q2e serve --port 8000
test: synth
	Rscript r/tests/run_tests.R
	python -m pytest -q tests
demo: synth
	python -m q2e examples --source synthetic --out outputs/examples
docker:
	docker compose up --build
