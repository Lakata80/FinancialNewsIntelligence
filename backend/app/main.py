from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.api.articles import router as articles_router
from app.api.debug import router as debug_router
from app.api.pipeline_api import router as pipeline_router
from app.api.stories import router as stories_router
from app.core.config import settings
from app.core.log_config import configure_logging

configure_logging(level=settings.log_level)

app = FastAPI(title="Financial News Intelligence")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(articles_router, prefix="/api")
app.include_router(stories_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(debug_router, prefix="/api")


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
