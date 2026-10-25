# The application in one image: the web frontend built with Node, served by the Python API.
#
#   docker build -t auditiq .
#   docker run -p 127.0.0.1:8000:8000 auditiq                         SQLite inside the container
#   docker compose -f deploy/docker-compose.yml up -d --build         with PostgreSQL (see that file)
#
# The project is installed where it is copied (/app), because the application reads its policy files, its
# datasets and the built frontend from there. It runs as an unprivileged user that can write only .auditiq/
# (the SQLite store, uploads and the model's response cache). Settings come from the environment, never .env.

FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AUDITIQ_NO_DOTENV=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY auditiq/ auditiq/
COPY auditiq_bench/ auditiq_bench/
COPY evaluation/ evaluation/
COPY app/ app/
COPY scripts/ scripts/
COPY policy/ policy/
COPY data/ data/
COPY results/ results/
RUN pip install --no-cache-dir -e . \
 && useradd --create-home --uid 1000 auditiq \
 && mkdir -p /app/.auditiq \
 && chown auditiq /app/.auditiq
COPY --from=frontend /build/dist frontend/dist
USER auditiq
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status != 200)"
CMD ["python", "-m", "auditiq", "serve", "--host", "0.0.0.0", "--port", "8000"]
