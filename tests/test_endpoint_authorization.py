"""Endpoint authorization matrix and RAG safety checks."""
import importlib

API_MODULES = [
    "bots", "chat", "documents", "document_upload", "conversations", "organizations", "auth",
]


def _all_api_routes():
    for mod in API_MODULES:
        m = importlib.import_module(f"eiraos.api.v1.{mod}")
        router = getattr(m, "router")
        for route in getattr(router, "routes", []):
            methods = getattr(route, "methods", None)
            if not methods:
                continue
            yield sorted(methods)[0], route.path, route


def _dependency_names(route) -> set:
    names = set()
    dependant = getattr(route, "dependant", None)
    for dep in (getattr(dependant, "dependencies", []) or []):
        qn = getattr(getattr(dep, "call", None), "__qualname__", "") or ""
        names.add(qn)
    return names


def test_no_write_route_is_anonymous():
    anonymous = []
    for method, path, route in _all_api_routes():
        if method not in ("POST", "PUT", "PATCH", "DELETE"):
            continue
        if "/auth/register" in path or "/auth/login" in path:
            continue
        names = _dependency_names(route)
        if not names & {"get_current_user", "require_permission.<locals>.permission_dependency", "get_current_active_organization"}:
            anonymous.append((method, path))
    assert anonymous == [], f"anonymous write routes: {anonymous}"


def test_all_endpoints_are_authenticated_or_auth_preflight():
    unauthed = []
    for method, path, route in _all_api_routes():
        if "/auth/register" in path or "/auth/login" in path:
            continue
        names = _dependency_names(route)
        if not names & {"get_current_user", "require_permission.<locals>.permission_dependency", "get_current_active_organization"}:
            unauthed.append((method, path))
    assert unauthed == [], f"unauthenticated endpoints: {unauthed}"


def test_mutating_bot_routes_require_permission():
    dirty = []
    for method, path, route in _all_api_routes():
        if "/bots" in path and method in ("POST", "PUT", "PATCH", "DELETE"):
            names = _dependency_names(route)
            if not any("permission_dependency" in n for n in names):
                dirty.append((method, path))
    assert dirty == [], f"bot mutations missing permission: {dirty}"


def test_document_upload_requires_permission():
    matches = [route for method, path, route in _all_api_routes() if method == "POST" and path == "/documents/upload"]
    assert len(matches) == 1
    assert any("permission_dependency" in n for n in _dependency_names(matches[0]))


def test_auth_identity_routes_are_brute_force_limited():
    limited = {}
    for method, path, route in _all_api_routes():
        if "auth/" in path and method == "POST":
            limited[path] = hasattr(route.endpoint, "__wrapped__")
    assert limited.get("/auth/login") is True
    assert limited.get("/auth/register") is True


def test_rate_limit_constants_are_production_sane():
    from eiraos.core import ratelimit
    assert ratelimit.AUTH_LOGIN_LIMIT == "5/minute"
    assert ratelimit.AUTH_REGISTER_LIMIT == "5/minute"


def test_intelligent_chunking_produces_content():
    from eiraos.domains.documents.rag_service import RAGService
    text = "\n\n".join(f"Paragraph {i}: " + ("word " * 80) for i in range(5))
    chunks = RAGService.intelligent_chunking(text, chunk_size=300, overlap=30)
    assert chunks and all(len(c) > 0 for c in chunks)


def test_intelligent_chunking_preserves_sections():
    from eiraos.domains.documents.rag_service import RAGService
    text = "Alpha content.\n\nBeta content.\n\nGamma content."
    chunks = RAGService.intelligent_chunking(text, chunk_size=50, overlap=0)
    joined = " ".join(chunks)
    assert "Alpha content" in joined
    assert "Gamma content" in joined
