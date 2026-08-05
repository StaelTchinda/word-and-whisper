# Everything under data/ is downloaded or generated. `make setup` produces all
# of it from scratch; `make data` alone takes about a second.
PY ?= venv/bin/python
PRAYER_DATA_URL ?=

.PHONY: help install fetch check-url data text index golden queries setup serve bench test clean distclean

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | expand -t22

install:  ## install the package and its runtime dependencies
	$(PY) -m pip install -e .[dev]

fetch:  ## download the source markdown (.zip or .tar.gz) into data/input/
	@$(PY) -m prayer.extract.fetch

check-url:  ## verify PRAYER_DATA_URL serves the archive, before pushing
	@$(PY) -m prayer.extract.fetch --check

data:  ## build the datasets from data/input/ (stdlib only, ~1s)
	$(PY) -m prayer.extract

text:  ## resolve every reference to World English Bible text
	$(PY) -m prayer.extract.text

index:  ## download the embedding model and precompute the vectors
	$(PY) -m prayer.api.build.index --download

golden:  ## regenerate the deterministic-composer golden fixtures
	$(PY) -m prayer.api.build.golden

queries:  ## regenerate the Tier 1 known-item query set
	$(PY) -m prayer.bench.build_tier1

setup: data text index queries golden  ## build everything data/input/ implies
	@echo "setup complete"

serve:  ## run the API
	$(PY) -m prayer.api

kill-serve:  ## kill the API
	@pids="$$(ps aux | grep 'python -m prayer.api' | grep -v grep | awk '{print $$2}')"; \
	if [ -n "$$pids" ]; then kill -9 $$pids; else echo "no prayer.api process running"; fi

bench:  ## run the evaluation matrix
	$(PY) -m prayer.bench.run

test:  ## run the test suite
	$(PY) -m pytest -q

clean:  ## remove everything a command can regenerate
	rm -rf data/build

distclean: clean  ## also remove downloads (input, scans, vendor)
	rm -rf data/input data/vendor
