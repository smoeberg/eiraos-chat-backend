# EiraOS Chat Backend - Production Deployment Runbook

## Overview
This runbook guides system operators through deploying and managing the enterprise-grade FastAPI backend for EiraOS in production Kubernetes clusters.

## Prerequisites
- Kubernetes cluster (v1.26+)
- PostgreSQL 16+ cluster with `pgvector` extension enabled
- Redis cluster (for ARQ job queues and session caching)
- Ingress Controller (e.g., NGINX Ingress or Traefik)

## Deployment Steps
1. **Create Namespace & Secrets:**
   ```bash
   kubectl create namespace eiraos-production
   kubectl create secret generic eiraos-secrets \
     --from-literal=database-url='postgresql+asyncpg://user:pass@postgres-host:5432/db' \
     --from-literal=redis-url='redis://redis-host:6379/0' \
     --from-literal=jwt-secret-key='your-super-secure-production-secret-key' \
     -n eiraos-production
   ```

2. **Apply Kubernetes Manifests:**
   ```bash
   kubectl -n eiraos-production apply -f deploy/k8s/
   ```

   Pin both backend and worker to the exact image digest qualified in staging;
   never deploy the mutable `latest` tag in production.
   Set `TRUSTED_PROXY_CIDRS` to only the ingress-controller source CIDRs. The
   application disables Uvicorn proxy-header rewriting and validates the
   forwarding chain itself; never use `0.0.0.0/0` or `::/0`.

3. **Verify Deployment & Health:**
   ```bash
   kubectl get pods -n eiraos-production
   curl https://api.eiraos.ai/health
   ```

## Observability & Metrics
- **Prometheus Metrics:** Exposed at `/metrics` (automatically scraped by Prometheus operators).
- **Structured JSON Logs:** Outputted to stdout, compatible with Datadog, ELK, and Grafana Loki.

## Release gate

Run migrations from the same qualified image before rollout, wait for backend
and worker deployments, require `/health/ready` HTTP 200, then execute
`scripts/gate12_staging_smoke.sh`. Roll back the deployment if any step fails;
database rollback requires a separately reviewed migration plan.
