# EiraOS Enterprise Chat Backend

EiraOS Chat Backend is a robust, asynchronous, multi-tenant AI and RAG chat platform built with Python, FastAPI, SQLAlchemy 2.0, PostgreSQL (`pgvector`), Redis, and ARQ.

## 🚀 Key Features

- **Multi-Tenant Architecture:** Strict database-level tenant isolation and membership validation (`OrganizationMember`) preventing IDOR and header spoofing.
- **Unified AI Gateway:** Standardized `AIProviderProtocol` supporting OpenAI, Anthropic Claude, and Google Gemini with Server-Sent Events (SSE) streaming.
- **Advanced RAG Pipeline:** Intelligent semantic text chunking, OpenAI embeddings, vector storage in PostgreSQL via `pgvector`, and cosinus-distance hybrid search.
- **Enterprise Security & Hardening:** JWT authentication, bcrypt password hashing, SlowAPI rate limiting, structured JSON logging (`structlog`), Prometheus metrics, and robust PostgreSQL/Redis health probes.
- **Asynchronous Background Workers:** ARQ + Redis worker integration for document ingestion and usage aggregation.

---

## 🛠️ Tech Stack

- **Framework:** FastAPI (Python 3.11+)
- **Database & Search:** PostgreSQL 16 + `pgvector`
- **ORM:** SQLAlchemy 2.0 (Async) + Alembic
- **Caching & Job Queue:** Redis + ARQ
- **AI Providers:** OpenAI, Anthropic Claude, Google Gemini

---

## ⚙️ Quickstart & Local Development

### 1. Prerequisites
- Docker & Docker Compose
- Python 3.11+

### 2. Environment Setup
Create a `.env` file in the root directory:
```env
PROJECT_NAME=EiraOS Chat Backend
API_V1_STR=/api/v1
SECRET_KEY=your-super-secret-production-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/eiraos
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=sk-...
```

### 3. Run with Docker Compose
```bash
docker-compose up --build
```
This will start PostgreSQL with `pgvector`, Redis, the ARQ worker, and the FastAPI application on `http://localhost:8000`.
- API Docs (Swagger): `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`
- Prometheus Metrics: `http://localhost:8000/metrics`

---

## 📂 Project Structure

```
src/eiraos/
├── api/v1/          # FastAPI routers (auth, chat, documents, conversations, bots, organizations)
├── application/     # AI Provider Protocol, Adapters & Factory
├── core/            # Config, database, exceptions, middleware, security
├── domains/         # Domain-Driven Design models (identity, organizations, documents, conversations, bots)
└── workers/         # ARQ background task workers
```

---

## 🛡️ License
MIT License. Developed for EiraOS Enterprise.
