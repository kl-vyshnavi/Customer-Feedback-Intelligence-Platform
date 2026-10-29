import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.core.config import get_settings
from app.db import Base, engine
from app import models  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


settings = get_settings()
app = FastAPI(
    title="Customer Feedback Intelligence Platform",
    description="Import, classify, cluster, and prioritize customer feedback with evidence.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)
app.include_router(router)
