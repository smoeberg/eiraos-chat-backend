# Staging Deploy Runbook — EiraOS Chat Backend

**Goal:** Deploy `main` to staging, verify Gate 0–2, enable GO/NO-GO for production.

---

## Quick path (recommended)

On a machine with Docker + kubectl + registry auth:

```bash
git pull origin main
export DATABASE_URL='postgresql+asyncpg://...'
export REDIS_URL='redis://...'
export SECRET_KEY="$(openssl rand -hex 32)"
export TRUSTED_PROXY_CIDRS='10.20.0.0/16' # replace with the actual ingress CIDR(s)
# optional: REGISTRY, NS, DEPLOY_NAME, BASE_URL, EMAIL, PASSWORD
chmod +x deploy/staging_deploy.sh
./deploy/staging_deploy.sh
```

Script: [`deploy/staging_deploy.sh`](staging_deploy.sh) — build → push → secrets → apply → migrate → smoke.
Validated with `bash -n` (LF line endings, complete `if`/`fi` blocks).

---

## 0. Prerequisites

| Item | Example |
|------|---------|
| Cluster access | `kubectl config current-context` |
| Namespace | `eiraos-staging` |
| Image registry | `ghcr.io/<org>/eiraos-chat-backend` |
| Secrets | `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, provider keys |
| Ingress identity | Actual ingress CIDR(s) in `TRUSTED_PROXY_CIDRS` |
| Postgres | pgvector-enabled 16+ |
| Redis | 7+ |

```bash
export NS=eiraos-staging
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
```

---

## 1. Build & push image

```bash
git checkout main && git pull origin main
export GIT_SHA=$(git rev-parse --short HEAD)
export IMAGE=ghcr.io/<org>/eiraos-chat-backend:$GIT_SHA

docker build -t "$IMAGE" .
docker push "$IMAGE"
```

Pin by digest in production later; tag by SHA is enough for staging.

---

## 2. Secrets

```bash
kubectl -n "$NS" create secret generic eiraos-secrets \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=DATABASE_URL='postgresql+asyncpg://user:pass@pg-host:5432/eiraos' \
  --from-literal=REDIS_URL='redis://redis:6379/0' \
  --from-literal=OPENAI_API_KEY='sk-...' \
  --dry-run=client -o yaml | kubectl apply -f -
```

Never commit secret values. Prefer External Secrets / Vault CSI when available.

---

## 3. Database migration

Handled by `staging_deploy.sh`, or manually:

```bash
kubectl -n "$NS" run eiraos-migrate --rm -it --restart=Never \
  --image="$IMAGE" \
  --env="DATABASE_URL=$(kubectl -n $NS get secret eiraos-secrets -o jsonpath='{.data.DATABASE_URL}' | base64 -d)" \
  --command -- alembic upgrade head
```

---

## 4. Apply Kubernetes manifests

```bash
kubectl -n "$NS" apply -f deploy/k8s/networkpolicy.yaml
kubectl -n "$NS" apply -f deploy/k8s/service.yaml
kubectl -n "$NS" apply -f deploy/k8s/deployment.yaml
kubectl -n "$NS" apply -f deploy/k8s/hpa.yaml
kubectl -n "$NS" rollout status deployment/eiraos-chat-backend --timeout=180s
```

Ensure **worker** is running: `arq eiraos.workers.tasks.WorkerSettings`.

---

## 5. Smoke — Gate 0–2

```bash
export BASE_URL=https://api.staging.example.com
export EMAIL=...
export PASSWORD=...

chmod +x scripts/gate12_staging_smoke.sh
./scripts/gate12_staging_smoke.sh

pip install -e ".[test]"
pytest -q tests/test_production_qualification_gate12.py tests/test_idempotency_fencing.py
```

---

## 6. Manual checklist (5 minutes)

| Check | Expected |
|-------|----------|
| `GET /health/live` | 200 |
| `GET /health/ready` | 200 (db+redis connected) |
| No token → organizations | 401 |
| No token → `/metrics` | 401/403 |
| Login | access_token |
| Ingest + Idempotency-Key | 202; replay stable |
| Chat SSE | start → tokens → done |
| Abort SSE mid-stream | status `cancelled`, not stuck `streaming` |

---

## 7. Rollback

```bash
kubectl -n "$NS" rollout undo deployment/eiraos-chat-backend
kubectl -n "$NS" rollout status deployment/eiraos-chat-backend --timeout=180s
```

---

## 8. GO / NO-GO

**GO:** Ready pods, smoke OK, no stuck streaming rows, secrets from K8s/Vault only.

**NO-GO:** Ready fails, 500s on core paths, public metrics, worker idle with queued jobs.

---

## 9. Promote to production

1. Same image digest as staging  
2. Strong secrets + no dev CORS  
3. `APP_ENV=production`  
4. `ALLOW_SYNC_INGEST_FALLBACK=false`  
5. NetworkPolicy + limits confirmed  
