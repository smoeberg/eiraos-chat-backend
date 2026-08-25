#!/usr/bin/env bash
# Staging deploy — build, push, migrate, apply, smoke.
# Run on a machine with: docker, kubectl, registry auth, cluster context.
#
# Required env:
#   DATABASE_URL, REDIS_URL, SECRET_KEY, TRUSTED_PROXY_CIDRS
# Optional:
#   REGISTRY, IMAGE_NAME, NS, OPENAI_API_KEY, CORS_ORIGINS, TRUSTED_HOSTS,
#   BASE_URL, EMAIL, PASSWORD
#
# Usage:
#   export DATABASE_URL=postgresql+asyncpg://...
#   export REDIS_URL=redis://...
#   export SECRET_KEY="$(openssl rand -hex 32)"
#   export TRUSTED_PROXY_CIDRS=10.20.0.0/16  # actual ingress CIDR(s)
#   ./deploy/staging_deploy.sh
set -euo pipefail

# ---------- configure ----------
NS="${NS:-eiraos-staging}"
REGISTRY="${REGISTRY:-ghcr.io/smoeberg}"
IMAGE_NAME="${IMAGE_NAME:-eiraos-chat-backend}"
GIT_SHA="$(git rev-parse HEAD)"
IMAGE="${REGISTRY}/${IMAGE_NAME}:${GIT_SHA}"

# Deployment / service names (override if manifests differ)
DEPLOY_NAME="${DEPLOY_NAME:-eiraos-chat-backend}"
SVC_NAME="${SVC_NAME:-eiraos-chat-backend-svc}"
CONTAINER_NAME="${CONTAINER_NAME:-backend}"

: "${DATABASE_URL:?Set DATABASE_URL (postgresql+asyncpg://...)}"
: "${REDIS_URL:?Set REDIS_URL (redis://...)}"
: "${SECRET_KEY:?Set SECRET_KEY (e.g. openssl rand -hex 32)}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
CORS_ORIGINS="${CORS_ORIGINS:-https://app.staging.eiraos.ai}"
TRUSTED_HOSTS="${TRUSTED_HOSTS:-api.staging.eiraos.ai,127.0.0.1}"
: "${TRUSTED_PROXY_CIDRS:?Set TRUSTED_PROXY_CIDRS to the staging ingress proxy CIDR(s)}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Image: $IMAGE"
echo "==> Namespace: $NS"

# ---------- 0. namespace ----------
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -

# ---------- 1. build & push ----------
docker build -t "$IMAGE" .
docker push "$IMAGE"

# ---------- 2. secrets ----------
kubectl -n "$NS" create secret generic eiraos-secrets \
  --from-literal=jwt-secret-key="$SECRET_KEY" \
  --from-literal=database-url="$DATABASE_URL" \
  --from-literal=redis-url="$REDIS_URL" \
  --from-literal=openai-api-key="$OPENAI_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

# ---------- 3. manifests ----------
kubectl -n "$NS" apply -f deploy/k8s/networkpolicy.yaml
kubectl -n "$NS" apply -f deploy/k8s/worker-networkpolicy.yaml
kubectl -n "$NS" apply -f deploy/k8s/service.yaml
kubectl -n "$NS" apply -f deploy/k8s/deployment.yaml
kubectl -n "$NS" apply -f deploy/k8s/worker.yaml
kubectl -n "$NS" apply -f deploy/k8s/hpa.yaml

# Point deployment at the image we just pushed
if kubectl -n "$NS" get "deployment/${DEPLOY_NAME}" >/dev/null 2>&1; then
  kubectl -n "$NS" set env "deployment/${DEPLOY_NAME}" \
    APP_ENV=staging RELEASE_SHA="$GIT_SHA" \
    CORS_ORIGINS="$CORS_ORIGINS" TRUSTED_HOSTS="$TRUSTED_HOSTS" \
    TRUSTED_PROXY_CIDRS="$TRUSTED_PROXY_CIDRS"
  kubectl -n "$NS" set image "deployment/${DEPLOY_NAME}" \
    "${CONTAINER_NAME}=${IMAGE}" \
    || kubectl -n "$NS" set image "deployment/${DEPLOY_NAME}" "*=${IMAGE}"
else
  echo "WARN: deployment/${DEPLOY_NAME} not found after apply — check deploy/k8s/deployment.yaml metadata.name"
  kubectl -n "$NS" get deploy
fi
kubectl -n "$NS" set env deployment/eiraos-worker \
  APP_ENV=staging RELEASE_SHA="$GIT_SHA" \
  CORS_ORIGINS="$CORS_ORIGINS" TRUSTED_HOSTS="$TRUSTED_HOSTS" \
  TRUSTED_PROXY_CIDRS="$TRUSTED_PROXY_CIDRS"
kubectl -n "$NS" set image deployment/eiraos-worker worker="$IMAGE"

# ---------- 4. migrate (one-off pod) ----------
kubectl -n "$NS" delete pod eiraos-migrate --ignore-not-found >/dev/null 2>&1 || true
kubectl -n "$NS" run eiraos-migrate --rm -i --restart=Never \
  --image="$IMAGE" \
  --overrides="{
    \"spec\": {
      \"containers\": [{
        \"name\": \"migrate\",
        \"image\": \"${IMAGE}\",
        \"command\": [\"alembic\", \"upgrade\", \"head\"],
        \"env\": [
          {\"name\": \"APP_ENV\", \"value\": \"staging\"},
          {\"name\": \"DATABASE_URL\", \"valueFrom\": {\"secretKeyRef\": {\"name\": \"eiraos-secrets\", \"key\": \"database-url\"}}},
          {\"name\": \"SECRET_KEY\", \"valueFrom\": {\"secretKeyRef\": {\"name\": \"eiraos-secrets\", \"key\": \"jwt-secret-key\"}}},
          {\"name\": \"REDIS_URL\", \"valueFrom\": {\"secretKeyRef\": {\"name\": \"eiraos-secrets\", \"key\": \"redis-url\"}}}
        ]
      }],
      \"restartPolicy\": \"Never\"
    }
  }"

# ---------- 5. wait for rollout ----------
if kubectl -n "$NS" get "deployment/${DEPLOY_NAME}" >/dev/null 2>&1; then
  kubectl -n "$NS" rollout status "deployment/${DEPLOY_NAME}" --timeout=180s
fi
kubectl -n "$NS" rollout status deployment/eiraos-worker --timeout=180s
kubectl -n "$NS" get pods -o wide

# ---------- 6. smoke ----------
PF_PID=""
if [[ -z "${BASE_URL:-}" ]]; then
  if kubectl -n "$NS" get "svc/${SVC_NAME}" >/dev/null 2>&1; then
    kubectl -n "$NS" port-forward "svc/${SVC_NAME}" 8000:80 &
    PF_PID=$!
    sleep 3
    BASE_URL="http://127.0.0.1:8000"
  else
    echo "WARN: no BASE_URL and svc/${SVC_NAME} missing — skip smoke"
  fi
fi

if [[ -n "${BASE_URL:-}" ]]; then
  export BASE_URL
  chmod +x scripts/gate12_staging_smoke.sh
  ./scripts/gate12_staging_smoke.sh
  python3 scripts/f8_performance_gate.py \
    --base-url "$BASE_URL" --require-release "$GIT_SHA"
fi

if [[ -n "${PF_PID}" ]]; then
  kill "${PF_PID}" 2>/dev/null || true
fi

echo "Deploy OK — image ${IMAGE}"
