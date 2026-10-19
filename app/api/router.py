from fastapi import APIRouter

from app.api.routes import audit, diagnostics, events, health, integrations, metrics, processes, services

api_router = APIRouter(prefix="/api")
for modulo in (health, metrics, processes, services, events, diagnostics, integrations, audit):
    api_router.include_router(modulo.router)
