from fastapi import APIRouter
from eiraos.api.v1.chat import router as chat_router
from eiraos.api.v1.auth import router as auth_router
from eiraos.api.v1.documents import router as documents_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(chat_router)
api_router.include_router(documents_router)
