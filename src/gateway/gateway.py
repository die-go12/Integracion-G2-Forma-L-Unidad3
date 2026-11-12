"""API Gateway: single entry point (routing, token auth, rate limiting)."""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from database import init_db, get_db
import uvicorn

PORT=os.getenv("PORT", 8080)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="API Gateway", lifespan=lifespan)

@app.get("/v1/health")
def health():
    return {"service": "gateway", "status": "ok"}



if __name__ == "__main__":
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
