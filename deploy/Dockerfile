# Build from the repository root:
#   docker build -f deploy/Dockerfile --build-arg PRAYER_DATA_URL=… -t prayer .
#
# The image builds its own data rather than shipping a prebuilt artifact: the
# extractors are stdlib-only and the whole build takes about a second, so there
# is nothing to gain from publishing one. Doing it here rather than at container
# start means a bad input fails the build instead of crash-looping the service.
#
# Layers are ordered so the two big, slow-changing pieces cache: dependencies
# first, then the 128 MB embedding model, then the data, then the code.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PRAYER_ROOT=/app \
    PRAYER_HOST=0.0.0.0 \
    PRAYER_PORT=8000

WORKDIR /app

# --- dependencies (changes rarely) ------------------------------------------
COPY pyproject.toml ./
COPY src/prayer/__init__.py src/prayer/__init__.py
RUN pip install --no-cache-dir -e . && rm -rf /root/.cache/pip

# --- code and curated policy -------------------------------------------------
COPY src/ src/
COPY policy/ policy/
COPY configs/ configs/

# --- embedding model (~128 MB, changes almost never) -------------------------
RUN python -c "from prayer.api.build.index import download_model; \
from prayer import paths; download_model(paths.EMBEDDING_MODEL)"

# --- data: fetch the sources, then build everything from them ----------------
# The books are copyrighted and are not in the repository. Supply a URL to an
# archive of data/input/. Without it the build stops here rather than producing
# an image that would fail at runtime.
ARG PRAYER_DATA_URL
# Optional bearer token, for an archive in a private repo. Empty for a
# pre-signed URL, which carries its own authentication.
ARG PRAYER_DATA_TOKEN=""
ENV PRAYER_DATA_URL=$PRAYER_DATA_URL PRAYER_DATA_TOKEN=$PRAYER_DATA_TOKEN
RUN python -m prayer.extract.fetch \
 && python -m prayer.extract --quiet \
 && python -m prayer.extract.text --quiet \
 && python -m prayer.api.build.index \
 && rm -rf data/input data/vendor/web
# Do not leave the credentials in the running container's environment.
ENV PRAYER_DATA_URL="" PRAYER_DATA_TOKEN=""

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import urllib.request,json,sys; \
r=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health')); \
sys.exit(0 if r.get('status')=='ok' else 1)"

CMD ["python", "-m", "prayer.api"]
