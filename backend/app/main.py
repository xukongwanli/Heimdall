from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import listings, metrics, search

app = FastAPI(title="Heimdall", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(listings.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(search.router, prefix="/api")
