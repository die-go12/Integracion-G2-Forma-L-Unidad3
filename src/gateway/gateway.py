"""API Gateway: single entry point (routing, token auth, rate limiting)."""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
import uvicorn
from database import init_db
from router import auth
from limiter import limiter


PORT=os.getenv("PORT", 8000)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="API Gateway", lifespan=lifespan)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Manejador personalizado cuando se excede el limite
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "codigo": "ERR_429",
            "mensaje": f"Demasiadas peticiones. Límite excedido: {exc.detail}."
        },
        headers={"Retry-After": "60"}
    )

@app.get("/v1/health")
def health():
    return {"service": "gateway", "status": "ok"}

app.include_router(auth.router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
