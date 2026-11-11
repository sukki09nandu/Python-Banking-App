#!/usr/bin/env bash
# Run the browser (UI) tests against a FRESH Postgres + app, all in Docker.
# Nothing is installed on the host; containers are removed afterwards.
# Screenshots: e2e/screenshots/*.png
set -euo pipefail
cd "$(dirname "$0")/.."

NET=bank-e2e-net PG=bank-e2e-pg API=bank-e2e-api
PW_IMAGE=mcr.microsoft.com/playwright/python:v1.64.1-noble

cleanup() { docker rm -f "$API" "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

docker network create "$NET" >/dev/null
docker run -d --rm --name "$PG" --network "$NET" \
  -e POSTGRES_PASSWORD=localdevonly -e POSTGRES_DB=banking postgres:17-alpine >/dev/null
until docker exec "$PG" pg_isready -U postgres -d banking -q; do sleep 1; done

docker run -d --rm --name "$API" --network "$NET" -v "$PWD":/src:ro -w /src \
  -e PYTHONDONTWRITEBYTECODE=1 -e SEED_DEMO_DATA=true \
  -e DATABASE_URL="postgresql+psycopg://postgres:localdevonly@$PG:5432/banking" \
  python:3.13-slim sh -c "pip install -q --root-user-action=ignore -r requirements.txt && \
                          uvicorn app.main:app --host 0.0.0.0 --port 8000" >/dev/null

echo "waiting for app to become ready..."
for _ in $(seq 1 90); do
  docker run --rm --network "$NET" curlimages/curl:8.11.1 -sf "http://$API:8000/health/ready" >/dev/null 2>&1 && break
  sleep 2
done

docker run --rm --network "$NET" --ipc=host -v "$PWD":/src -w /src \
  -e PYTHONDONTWRITEBYTECODE=1 -e BASE_URL="http://$API:8000" "$PW_IMAGE" \
  sh -c "pip install -q --break-system-packages playwright==1.64.1 pytest==9.2.0 >/dev/null 2>&1; \
         pytest -v -p no:cacheprovider e2e; rc=\$?; chown -R $(id -u):$(id -g) e2e; exit \$rc"
