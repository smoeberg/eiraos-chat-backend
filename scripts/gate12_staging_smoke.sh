#!/usr/bin/env bash
# Gate 1–2 smoke against a running staging/API instance.
# Usage:
#   export BASE_URL=https://api.staging.example.com
#   export EMAIL=admin@example.com
#   export PASSWORD='***'
#   ./scripts/gate12_staging_smoke.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
API="${BASE_URL%/}/api/v1"

echo "== G0 health =="
curl -fsS "$BASE_URL/health/live" | head -c 200; echo
READY_CODE=$(curl -s -o /tmp/ready.json -w "%{http_code}" "$BASE_URL/health/ready")
echo "ready HTTP $READY_CODE"
cat /tmp/ready.json; echo

echo "== G1 unauthenticated must fail =="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API/organizations")
test "$CODE" = "401" || { echo "FAIL organizations expected 401 got $CODE"; exit 1; }

CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/metrics")
test "$CODE" = "401" -o "$CODE" = "403" || { echo "FAIL metrics expected 401/403 got $CODE"; exit 1; }

if [[ -z "${EMAIL:-}" || -z "${PASSWORD:-}" ]]; then
  echo "Skip authenticated checks (set EMAIL + PASSWORD to enable)"
  echo "OK (partial)"
  exit 0
fi

echo "== Login =="
TOKEN=$(curl -fsS -X POST "$API/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$EMAIL&password=$PASSWORD" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")
test -n "$TOKEN" || { echo "FAIL login"; exit 1; }

AUTH="Authorization: Bearer $TOKEN"

echo "== Authenticated org list =="
curl -fsS -H "$AUTH" "$API/organizations" | head -c 300; echo

echo "== Idempotency replay (documents ingest if permitted) =="
KEY="smoke-$(date +%s)"
BODY='{"title":"gate12-smoke","content":"hello world smoke document"}'
R1=$(curl -s -o /tmp/ing1.json -w "%{http_code}" -X POST "$API/documents/ingest" \
  -H "$AUTH" -H "Content-Type: application/json" -H "Idempotency-Key: $KEY" \
  -d "$BODY")
R2=$(curl -s -o /tmp/ing2.json -w "%{http_code}" -X POST "$API/documents/ingest" \
  -H "$AUTH" -H "Content-Type: application/json" -H "Idempotency-Key: $KEY" \
  -d "$BODY")
echo "first=$R1 second=$R2"
cat /tmp/ing1.json; echo
cat /tmp/ing2.json; echo

echo "OK gate12 staging smoke"
