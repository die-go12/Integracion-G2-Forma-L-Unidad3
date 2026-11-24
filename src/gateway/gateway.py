"""API Gateway: punto de entrada único del sistema.

Responsabilidades:
  - Autenticación JWT (token emitido por /v1/auth/login).
  - Rate limiting global y por endpoint.
  - Enrutamiento de las rutas de negocio hacia el BFF.
  - Respuestas de error normalizadas.
"""

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
import uvicorn

from database import init_db
from router import auth
from limiter import limiter
from auth import obtener_usuario_actual

PORT   = int(os.getenv("PORT", 8000))
BFF_URL = os.getenv("BFF_URL", "http://bff:5005")
TIMEOUT = float(os.getenv("GATEWAY_TIMEOUT", "15.0"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="API Gateway", lifespan=lifespan)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


# ─── Manejadores de error normalizados ──────────────────────────────────────

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


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/v1/health")
def health():
    return {"service": "gateway", "status": "ok"}


# ─── Autenticación (pública) ─────────────────────────────────────────────────

app.include_router(auth.router)


# ─── Proxy hacia el BFF (requiere JWT válido) ────────────────────────────────

async def _proxy(
    request: Request,
    bff_path: str,
    usuario: dict = Depends(obtener_usuario_actual),
) -> JSONResponse:
    """
    Reenvía la petición autenticada al BFF conservando método, body y
    cabeceras relevantes. Agrega X-User y X-Role para que el BFF pueda
    aplicar lógica por perfil si lo necesita.
    """
    url = f"{BFF_URL}{bff_path}"
    method = request.method
    body = await request.body()

    headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "X-User":       usuario.get("username", ""),
        "X-Role":       usuario.get("rol", ""),
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.request(method, url, content=body, headers=headers)
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"codigo": "ERR_504", "mensaje": "El servicio no respondió a tiempo."}
        )
    except httpx.RequestError as exc:
        return JSONResponse(
            status_code=503,
            content={"codigo": "ERR_503", "mensaje": f"Servicio no disponible: {type(exc).__name__}"}
        )

    # Reenvía la respuesta del BFF tal cual (código + cuerpo JSON)
    try:
        content = resp.json()
    except Exception:
        content = {"raw": resp.text}

    return JSONResponse(status_code=resp.status_code, content=content)


@app.post("/v1/envios", status_code=201)
@limiter.limit("30/minute")
async def crear_envio(request: Request, usuario: dict = Depends(obtener_usuario_actual)):
    """Crea un nuevo envío. Redirige al BFF tras autenticar."""
    return await _proxy(request, "/envios", usuario)


@app.get("/v1/envios/{envio_id}")
@limiter.limit("60/minute")
async def consultar_envio(envio_id: str, request: Request, usuario: dict = Depends(obtener_usuario_actual)):
    """Consulta el estado de un envío. Redirige al BFF tras autenticar."""
    return await _proxy(request, f"/envios/{envio_id}", usuario)


@app.get("/v1/resiliencia")
@limiter.limit("30/minute")
async def estado_resiliencia(request: Request, usuario: dict = Depends(obtener_usuario_actual)):
    """Expone las métricas de resiliencia del sistema (circuit breaker, bulkhead)."""
    return await _proxy(request, "/resiliencia", usuario)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
