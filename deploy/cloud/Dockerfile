# Bowers Cloud: Bowie with no key, for the people you invite. Build from the repository root:
#   docker build -f deploy/cloud/Dockerfile -t bowers-cloud .
#   docker run -p 8790:8790 -e ANTHROPIC_API_KEY=... -v bowers-cloud:/data bowers-cloud
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY docks ./docks
RUN pip install --no-cache-dir .
ENV BOWERS_CLOUD_DB=/data/cloud.db BOWERS_VAULT=file DOCKS_HOME=/data/home
VOLUME /data
EXPOSE 8790
CMD ["sh", "-c", "mkdir -p /data && exec bowers cloud serve --host 0.0.0.0 --port ${PORT:-8790}"]
