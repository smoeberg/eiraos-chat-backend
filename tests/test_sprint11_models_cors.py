from eiraos.api.v1.chat import ChatCompletionRequest
from eiraos.api.v1.bots import BotCreateSchema
from eiraos.api.v1.documents import DocumentIngestRequest
from eiraos.api.v1.organizations import OrganizationCreateSchema


def test_inbound_models_reject_unknown_fields():
    from pydantic import ValidationError
    for model in (ChatCompletionRequest, BotCreateSchema, DocumentIngestRequest, OrganizationCreateSchema):
        assert model.model_config.get("extra") == "forbid"


def _cors_middleware(main_mod):
    return [m for m in main_mod.app.user_middleware if getattr(m.cls, "__name__", "") == "CORSMiddleware"]


def test_cors_uses_explicit_headers_not_wildcard():
    import eiraos.main
    mw = _cors_middleware(eiraos.main)[0]
    kwargs = mw.kwargs
    assert "*" not in kwargs["allow_headers"]
    assert "Authorization" in kwargs["allow_headers"]
