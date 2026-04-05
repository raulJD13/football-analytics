FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/     ./api/
COPY ml/      ./ml/
COPY dbt/     ./dbt/
COPY scripts/ ./scripts/
COPY infra/   ./infra/

ENV PYTHONPATH=/app
