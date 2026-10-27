# Chào Bà API (FastAPI + elder web-call page). Build from the repo root:
#   docker build -t chaoba-api .
#   docker run -p 8000:8000 -e CHAOBA_CORS_ORIGINS=http://localhost:3000 chaoba-api
# The prototype store is SQLite (CHAOBA_DB, re-seeded with simulated personas when empty). Postgres + RLS
# (chaoba/server/schema.sql) is the production schema target; see docker-compose.yml and deploy/.
# Python 3.14 to match the dev venv; if a 3.14 image is unavailable, PYTHON_VERSION=3.13 also works
# (numpy/pandas/pydantic wheels exist for both).
ARG PYTHON_VERSION=3.14
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CHAOBA_DB=/var/lib/chaoba/chaoba.db

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY chaoba ./chaoba
COPY data/eval ./data/eval

# Run as an unprivileged user; the SQLite file lives on a volume.
RUN useradd --system --uid 10001 --home /app chaoba \
 && mkdir -p /var/lib/chaoba && chown chaoba /var/lib/chaoba
USER chaoba
VOLUME ["/var/lib/chaoba"]

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"
# ANTHROPIC_API_KEY (optional) switches conversation/analysis to Claude; without it every LLM step uses its fallback.
CMD ["uvicorn", "chaoba.server.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
