from fastapi import FastAPI
from contextlib import asynccontextmanager
from starlette.middleware.cors import CORSMiddleware
from middleware.request_id import RequestIDMiddleware
from httpxC.http_client import http_client
from core.config import settings

# from cache.redis import redis_manager

from api.v1.api import api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # await redis_manager.connect()
    yield
    # Disconnect from clients on shutdown
    # await redis_manager.disconnect()
    await http_client.aclose()

app = FastAPI(
    title="The Watchtower API",
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")