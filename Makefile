# Thin delegator. The real backend build lives in backend/Makefile — this
# lets `make <target>` still work from the repo root (and keeps CI from
# needing `working-directory: backend` on every step). Command-line variable
# overrides (e.g. `make install PY=python`) propagate to the sub-make
# automatically via GNU Make's MAKEOVERRIDES.
.PHONY: help install fetch check-url data text index golden queries setup serve kill-serve bench test clean distclean frontend-install frontend-dev frontend-build

help:  ## list backend + frontend targets
	@grep -E '^[a-z-]+:.*?## ' backend/Makefile | sed 's/:.*## /\t/' | expand -t22
	@grep -E '^[a-z-]+:.*?## ' Makefile | sed 's/:.*## /\t/' | expand -t22

install fetch check-url data text index golden queries setup serve kill-serve bench test clean distclean:
	@$(MAKE) -C backend $@

frontend-install:  ## install the frontend's dependencies
	cd frontend && npm install

frontend-dev:  ## run the frontend dev server (proxies /api to :8000 -- run `make serve` alongside)
	cd frontend && npm run dev

frontend-build:  ## type-check and build the frontend for production
	cd frontend && npm run build
