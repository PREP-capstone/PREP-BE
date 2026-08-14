# RDS Sandbox Deployment

PREP-BE uses PostgreSQL for relational data and ChromaDB for vector embeddings.
In a sandbox deployment, AWS RDS PostgreSQL replaces the local Docker Postgres
container. ChromaDB should stay on the application server with persistent
storage.

## Environment

Do not commit `.env`. Set the deployment values on the server or in the
deployment platform's secret manager.

```env
APP_ENV=sandbox
DATABASE_URL=postgresql+asyncpg://prep_user:<password>@<rds-endpoint>:5432/postgres
REDIS_URL=redis://127.0.0.1:6379/0
OPENAI_API_KEY=<openai-api-key>
CHROMA_PERSIST_DIRECTORY=/app/data/chroma
CHROMA_COLLECTION_NAME=evidence_chunks
```

If the RDS database name is `prep`, use `/prep` instead of `/postgres`.

## AWS RDS Checklist

| Item | Value |
| --- | --- |
| Engine | PostgreSQL |
| Region | ap-northeast-2 |
| Public access | Yes for local sandbox testing |
| Security group inbound | PostgreSQL 5432 from My IP |
| Master username | prep_user |
| Database name | postgres or prep |

For production, disable public access and allow inbound traffic only from the
FastAPI server security group.

## Bootstrap Commands

Run from the project root after `.env` points at the RDS endpoint.

```bash
.venv/bin/python scripts/check_deploy_ready.py --skip-chroma
.venv/bin/alembic upgrade head
.venv/bin/python scripts/import_evidence_csv.py
.venv/bin/python scripts/seed_reference_data.py
.venv/bin/python scripts/import_postgres_seed_data.py
.venv/bin/python scripts/embed_evidence_chunks.py
.venv/bin/python scripts/check_deploy_ready.py
```

The first readiness check can fail on `evidence_tables` and `reference_tables`
before migrations, RAG CSV import, reference seed import, and Postgres catalog import have run. After bootstrapping,
all checks should pass.

Postgres catalog seed workbooks are read from `data/postgres/`:

```bash
.venv/bin/python scripts/import_postgres_seed_data.py --dry-run
.venv/bin/python scripts/import_postgres_seed_data.py
```

This imports `data_sensitivity`, `public_data_catalog`, `api_catalog`,
`trend_signal_config`, `action_templates`, `mvp_strategy_templates`,
`competitors`, and `bm_mapping`.

## ChromaDB Deployment

ChromaDB is not stored in RDS. It is stored in the path configured by
`CHROMA_PERSIST_DIRECTORY`.

For Docker deployments, mount this path as a persistent volume:

```yaml
volumes:
  - chroma_data:/app/data/chroma
```

Embeddings are generated from RDS `evidence_chunks` rows:

```bash
.venv/bin/python scripts/embed_evidence_chunks.py
```

Do not commit `data/chroma/`. It can be regenerated from RDS chunks and the
OpenAI embedding model.

## Verification

Start the API:

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

RAG search:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/rag/search \
  -H "Content-Type: application/json" \
  -d '{"query":"허위 과대 광고","top_k":5,"tag_advertising":true}'
```
