# Everything under data/ is downloaded or generated. `make setup` produces all
# of it from scratch; `make data` alone takes about a second.
PY ?= venv/bin/python
PRAYER_DATA_URL ?=

.PHONY: help install fetch data text index golden queries setup serve bench test clean distclean

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | expand -t22

install:  ## install the package and its runtime dependencies
	$(PY) -m pip install -e .[dev]

fetch:  ## download the cleaned source markdown into data/input/
	@if [ -z "$(PRAYER_DATA_URL)" ]; then \
	  echo "PRAYER_DATA_URL is not set."; \
	  echo "The source books are copyrighted and are not in this repository."; \
	  echo "Point it at an archive of data/input/, e.g.:"; \
	  echo "  make fetch PRAYER_DATA_URL=https://…/prayer-input.tar.gz"; \
	  exit 1; \
	fi
	@mkdir -p data/input
	@curl -fsSL "$(PRAYER_DATA_URL)" | tar -xz -C data/input
	@echo "input: $$(ls data/input | tr '\n' ' ')"

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

bench:  ## run the evaluation matrix
	$(PY) -m prayer.bench.run

test:  ## run the test suite
	$(PY) -m pytest -q

clean:  ## remove everything a command can regenerate
	rm -rf data/build

distclean: clean  ## also remove downloads (input, scans, vendor)
	rm -rf data/input data/vendor
