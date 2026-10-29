# Candidate hosted judge image; validate its ingress and storage before deployment.
FROM node:24.14.0-bookworm-slim AS node
FROM python:3.12.13-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
COPY incidentcourt /app/incidentcourt
COPY scripts/hmem_bridge.ts /app/scripts/hmem_bridge.ts
COPY scripts/prepare_container_sample.py /app/scripts/prepare_container_sample.py
COPY vendor/meterless-hmem /app/vendor/meterless-hmem
COPY data/sample.json.gz /app/data/sample.json.gz
COPY data/public/sample-manifest.json /app/data/public/sample-manifest.json
COPY deploy/instacloud /app/deploy/instacloud
RUN python -m scripts.prepare_container_sample /app/data/sample.sqlite3 \
    && useradd --create-home --uid 10001 investigator \
    && chown -R root:root /app && chmod -R a-w /app
USER investigator
# Fail the image build if the final service UID cannot read the public fixture.
RUN python -c "from incidentcourt.sample import ensure_sample_db; import sqlite3; p = ensure_sample_db('/app/data/sample.sqlite3'); c = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True); assert c.execute('SELECT count(*) FROM incidents').fetchone()[0] > 0; c.close()"
EXPOSE 8080
CMD ["python", "deploy/instacloud/start.py"]
