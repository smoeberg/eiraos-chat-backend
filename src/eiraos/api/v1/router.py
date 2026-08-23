from fastapi import APIRouter
from eiraos.api.v1.chat import router as chat_router
from eiraos.api.v1.auth import router as auth_router
from eiraos.api.v1.documents import router as documents_router
from eiraos.api.v1.document_upload import router as document_upload_router
from eiraos.api.v1.conversations import router as conversations_router
from eiraos.api.v1.bots import router as bots_router
from eiraos.api.v1.organizations import router as organizations_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(chat_router)
api_router.include_router(documents_router)
api_router.include_router(document_upload_router)
api_router.include_router(conversations_router)
api_router.include_router(bots_router)
api_router.include_router(organizations_router)
