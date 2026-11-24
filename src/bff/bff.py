"""BFF (Backend for Frontend): agrega datos de varios servicios y da forma a las
respuestas orientadas al cliente web/móvil.

Responsabilidades:
  - Ofrecer una interfaz de alto nivel (/envios) adaptada al cliente.
  - Llamar al orquestador y, si es necesario, a otros servicios para enriquecer.
  - Transformar errores internos en respuestas amigables.
  - Exponer un /health y un /resiliencia para observabilidad.
"""

import asyncio
import os
import logging
import sys

import httpx
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# URLs de los microservicios internos
ORQUESTADOR_URL = os.getenv("ORQUESTADOR_URL", "http://orquestador:5004")
TRANSPORTISTA_URL = os.getenv("TRANSPORTISTA_URL", "http://transportista:5002")
TRACKING_URL    = os.getenv("TRACKING_URL",    "http://tracking:5003")

TIMEOUT = float(os.getenv("BFF_TIMEOUT", "10.0"))
# Timeout corto para las consultas de detalle: son opcionales y no deben frenar la respuesta
TIMEOUT_DETALLE = float(os.getenv("BFF_TIMEOUT_DETALLE", "2.0"))

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [BFF] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("bff")

app = FastAPI(title="BFF – Backend for Frontend")


# ─── Schemas ────────────────────────────────────────────────────────────────

class CrearEnvioRequest(BaseModel):
    producto_id: int
    cantidad: int = Field(gt=0, description="Unidades a enviar (debe ser > 0)")
    envio_id: str | None = Field(
        default=None,
        description="Clave de idempotencia opcional. Si se omite, el orquestador la genera."
    )


# ─── Helpers ────────────────────────────────────────────────────────────────

def _cliente() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT)


def _formatear_envio(raw: dict) -> dict:
    """Transforma la respuesta interna del orquestador en una vista orientada al cliente."""
    estado = raw.get("estado", "DESCONOCIDO")

    # Mapa de estados internos → etiquetas amigables
    etiquetas = {
        "COMPLETADO": "Envío creado exitosamente",
        "COMPENSADO": "El envío no pudo completarse; los recursos han sido liberados",
        "COMPENSACION_INCOMPLETA": "Error crítico: compensación parcial. Contacte soporte",
        "EN_CURSO": "Envío en proceso",
    }

    respuesta = {
        "envio_id":           raw.get("envio_id"),
        "estado":             estado,
        "mensaje":            etiquetas.get(estado, f"Estado: {estado}"),
        "codigo_seguimiento": raw.get("codigo_seguimiento"),
        "codigo_retiro":      raw.get("codigo_retiro"),
    }

    # Información extra cuando hay degradación o fallo
    if raw.get("motivo"):
        respuesta["detalle_error"] = raw["motivo"]
    if raw.get("fallback"):
        respuesta["modo_degradado"] = raw["fallback"]

    return respuesta


async def _detalle(url: str) -> dict | None:
    """Consulta un servicio de dominio. Si no responde o no tiene el dato devuelve None:
    la respuesta agregada sale igual, con ese campo vacío."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_DETALLE) as client:
            resp = await client.get(url)
    except httpx.RequestError as exc:
        logger.warning(f"Detalle no disponible {url} ({type(exc).__name__})")
        return None
    return resp.json() if resp.status_code == 200 else None


# ─── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"service": "bff", "status": "ok"}


@app.post("/envios", status_code=201)
async def crear_envio(req: CrearEnvioRequest):
    """
    Crea un envío completo.

    Llama al orquestador (saga «crear envío») y adapta la respuesta
    al formato que espera el cliente.
    """
    payload = {"producto_id": req.producto_id, "cantidad": req.cantidad}
    if req.envio_id:
        payload["envio_id"] = req.envio_id

    logger.info(f"Solicitud crear_envio producto={req.producto_id} cantidad={req.cantidad}")

    try:
        async with _cliente() as client:
            resp = await client.post(f"{ORQUESTADOR_URL}/envios", json=payload)
    except httpx.TimeoutException:
        logger.error("Timeout al contactar orquestador")
        raise HTTPException(status_code=504, detail={
            "codigo": "ERR_504",
            "mensaje": "El servicio de envíos no respondió a tiempo. Intente nuevamente."
        })
    except httpx.RequestError as exc:
        logger.error(f"Error de red al contactar orquestador: {exc}")
        raise HTTPException(status_code=503, detail={
            "codigo": "ERR_503",
            "mensaje": "El servicio de envíos no está disponible en este momento."
        })

    raw = resp.json()
    logger.info(f"Orquestador respondió HTTP {resp.status_code} estado={raw.get('estado')}")

    # Errores de negocio (409 conflicto de stock, 404 producto no encontrado)
    if resp.status_code in (400, 404, 409):
        raise HTTPException(status_code=resp.status_code, detail={
            "codigo": f"ERR_{resp.status_code}",
            "mensaje": raw.get("detail", "Solicitud rechazada por el servicio de envíos.")
        })

    # Fallo de saga (compensaciones ejecutadas)
    if resp.status_code >= 500:
        return JSONResponse(
            status_code=503,
            content={
                "codigo": "ERR_503",
                "mensaje": "El envío no pudo completarse. Los recursos han sido liberados.",
                "detalle": _formatear_envio(raw),
            }
        )

    return JSONResponse(
        status_code=201,
        content=_formatear_envio(raw)
    )


@app.get("/envios/{envio_id}")
async def consultar_envio(envio_id: str):
    """
    Vista agregada de un envío: junta el estado de la saga (orquestador) con el
    retiro (Transportista) y el seguimiento (Tracking), consultados en paralelo.
    """
    logger.info(f"Consultar envio_id={envio_id}")

    try:
        async with _cliente() as client:
            resp = await client.get(f"{ORQUESTADOR_URL}/envios/{envio_id}")
    except httpx.RequestError as exc:
        logger.error(f"Error al consultar orquestador: {exc}")
        raise HTTPException(status_code=503, detail={
            "codigo": "ERR_503",
            "mensaje": "No se pudo consultar el estado del envío."
        })

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail={
            "codigo": "ERR_404",
            "mensaje": f"Envío '{envio_id}' no encontrado."
        })

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())

    raw = resp.json()
    respuesta = _formatear_envio(raw)

    # Enriquecimiento: agrega pasos completados y compensaciones como evidencia
    if raw.get("pasos"):
        respuesta["pasos_completados"] = raw["pasos"]
    if raw.get("compensaciones"):
        respuesta["compensaciones"] = raw["compensaciones"]

    # Agregación: estado real del retiro y del seguimiento, leído de cada servicio
    respuesta["retiro"], respuesta["seguimiento"] = await asyncio.gather(
        _detalle(f"{TRANSPORTISTA_URL}/retiros/{envio_id}"),
        _detalle(f"{TRACKING_URL}/tracking/{envio_id}"),
    )

    return respuesta


@app.get("/resiliencia")
async def estado_resiliencia():
    """Expone las métricas de resiliencia del orquestador (circuit breaker, bulkhead)."""
    try:
        async with _cliente() as client:
            resp = await client.get(f"{ORQUESTADOR_URL}/resiliencia")
        return resp.json()
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail={
            "codigo": "ERR_503",
            "mensaje": "No se pudo obtener el estado de resiliencia."
        })


if __name__ == "__main__":
    import uvicorn
    PORT = int(os.getenv("PORT", 5005))
    uvicorn.run(app, host="0.0.0.0", port=PORT)
