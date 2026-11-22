"""Orquestador de la Saga «crear envío»: ejecuta los pasos y compensa en orden inverso."""
import logging
import os
import sys
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from resiliencia.resiliencia import ResilienciaTransportista

INVENTARIO_URL = os.getenv("INVENTARIO_URL", "http://inventario:5001")
TRANSPORTISTA_URL = os.getenv("TRANSPORTISTA_URL", "http://transportista:5002")
TRACKING_URL = os.getenv("TRACKING_URL", "http://tracking:5003")

# Timeout de toda llamada entre servicios (segundos)
TIMEOUT = 2.0

# Logger propio para que los pasos de la saga se distingan de los de resiliencia
logger = logging.getLogger("saga")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [SAGA] %(message)s", "%Y-%m-%d %H:%M:%S"))
logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False

# Instancia global compartida por todas las peticiones del orquestador
protector_transportista = ResilienciaTransportista(
    max_concurrent=3,      # Máximo 3 llamadas simultáneas a Transportista
    failure_threshold=3,   # Al 3er fallo consecutivo se abre el circuito
    recovery_timeout=10.0, # Se mantiene abierto 10 segundos antes de probar
    request_timeout=TIMEOUT
)

def fallback_agendar_retiro(payload: dict, motivo: str) -> dict:
    # degradación cuando Transportista falla o está saturado:
    # se responde de inmediato en vez de esperar al servicio externo
    return {
        "status": "DEGRADADO",
        "agendado": False,
        "estado_retiro": "PENDIENTE_RETIRO_DIFERIDO",
        "motivo_fallback": motivo,
        "envio_id": payload.get("envio_id")
    }

app = FastAPI(title="orquestador")

# Estado de cada saga por envio_id. También da idempotencia: un envío repetido no se vuelve a ejecutar.
sagas: dict[str, dict] = {}


class CrearEnvioRequest(BaseModel):
    producto_id: int
    cantidad: int = Field(gt=0)
    envio_id: str | None = None  # clave de idempotencia; si no viene se genera


async def _post(url: str, payload: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        return await client.post(url, json=payload)


# La petición nunca llegó al servicio, así que no dejó nada que deshacer
NO_ENVIADA = (httpx.ConnectError, httpx.ConnectTimeout)


async def _compensar(envio_id: str, paso: str) -> str:
    """Deshace un paso. Las compensaciones son idempotentes; 404 = no había nada que deshacer.
    Devuelve "ok", "inalcanzable" (no se pudo conectar) o "fallida"."""
    url, payload = {
        "tracking": (f"{TRACKING_URL}/anular", {"envio_id": envio_id}),
        "transportista": (f"{TRANSPORTISTA_URL}/cancelar", {"envio_id": envio_id}),
        "inventario": (f"{INVENTARIO_URL}/compensar", {"saga_id": envio_id}),
    }[paso]
    try:
        resp = await _post(url, payload)
        if resp.status_code < 300 or resp.status_code == 404:
            logger.info(f"[{envio_id}] COMPENSADO {paso} (HTTP {resp.status_code})")
            return "ok"
        logger.error(f"[{envio_id}] COMPENSACION FALLIDA {paso} (HTTP {resp.status_code})")
    except NO_ENVIADA as exc:
        logger.error(f"[{envio_id}] COMPENSACION SIN CONEXION {paso} ({type(exc).__name__})")
        return "inalcanzable"
    except httpx.RequestError as exc:
        logger.error(f"[{envio_id}] COMPENSACION FALLIDA {paso} ({type(exc).__name__})")
    return "fallida"


async def _abortar(saga: dict, a_compensar: list[str], motivo: str, status_code: int) -> JSONResponse:
    """Compensa en orden inverso los pasos indicados y cierra la saga como fallida.
    Un paso que no está en saga["pasos"] es dudoso: falló, pero pudo alcanzar a ejecutarse.
    Si al compensarlo el servicio ni siquiera conecta, se asume que no dejó nada."""
    envio_id = saga["envio_id"]
    logger.warning(f"[{envio_id}] FALLO: {motivo}. Compensando en orden inverso: {a_compensar[::-1]}")
    todo_ok = True
    for paso in reversed(a_compensar):
        resultado = await _compensar(envio_id, paso)
        saga["compensaciones"].append({"paso": paso, "resultado": resultado})
        dudoso = paso not in saga["pasos"]
        todo_ok = todo_ok and (resultado == "ok" or (dudoso and resultado == "inalcanzable"))
    saga["estado"] = "COMPENSADO" if todo_ok else "COMPENSACION_INCOMPLETA"
    saga["motivo"] = motivo
    logger.warning(f"[{envio_id}] SAGA {saga['estado']}")
    return JSONResponse(status_code=status_code, content=saga)


@app.get("/health")
def health():
    return {"service": "orquestador", "status": "ok"}


@app.post("/envios", status_code=201)
async def crear_envio(req: CrearEnvioRequest):
    envio_id = req.envio_id or f"ENV-{uuid.uuid4().hex[:8].upper()}"

    # Idempotencia: el mismo envío no se ejecuta dos veces
    if envio_id in sagas:
        logger.info(f"[{envio_id}] Envío repetido, se devuelve el resultado anterior")
        return sagas[envio_id]

    saga = {"envio_id": envio_id, "estado": "EN_CURSO", "pasos": [], "compensaciones": []}
    sagas[envio_id] = saga
    logger.info(f"[{envio_id}] SAGA INICIADA producto={req.producto_id} cantidad={req.cantidad}")

    # Paso 1: Inventario reserva la mercadería
    try:
        resp = await _post(
            f"{INVENTARIO_URL}/reservar",
            {"saga_id": envio_id, "producto_id": req.producto_id, "cantidad": req.cantidad},
        )
    except httpx.RequestError as exc:
        # Si la petición alcanzó a salir, la reserva pudo quedar hecha: se compensa por si acaso
        dudosos = [] if isinstance(exc, NO_ENVIADA) else ["inventario"]
        return await _abortar(saga, dudosos, f"Inventario no responde ({type(exc).__name__})", 503)
    if resp.status_code in (400, 404):
        # Regla de negocio: no hay nada reservado, nada que compensar
        detalle = resp.json().get("detail", "Reserva rechazada")
        del sagas[envio_id]
        logger.warning(f"[{envio_id}] RECHAZADO por Inventario: {detalle}")
        raise HTTPException(status_code=409 if resp.status_code == 400 else 404, detail=detalle)
    if resp.status_code >= 300:
        return await _abortar(saga, ["inventario"], f"Inventario respondió HTTP {resp.status_code}", 502)
    saga["pasos"].append("inventario")
    logger.info(f"[{envio_id}] PASO 1 OK mercadería reservada")

    # Paso 2: Transportista agenda el retiro (dependencia frágil: bulkhead + circuit breaker + timeout)
    retiro = await protector_transportista.ejecutar_con_resiliencia(
        f"{TRANSPORTISTA_URL}/agendar", {"envio_id": envio_id}, fallback_agendar_retiro
    )
    if retiro.get("status") == "DEGRADADO":
        motivo = retiro["motivo_fallback"]
        # Si la llamada alcanzó a salir, el retiro pudo quedar agendado igual: se cancela.
        # Si la frenó el circuito o el bulkhead, nunca salió y no hay retiro que cancelar.
        a_compensar = ["inventario"]
        if motivo in ("TIMEOUT_TRANSPORTISTA", "TRANSPORTISTA_CAIDO"):
            a_compensar.append("transportista")
        saga["fallback"] = retiro
        return await _abortar(saga, a_compensar, f"Transportista no disponible ({motivo})", 503)
    saga["pasos"].append("transportista")
    saga["codigo_retiro"] = retiro.get("codigo_retiro")
    logger.info(f"[{envio_id}] PASO 2 OK retiro agendado {saga['codigo_retiro']}")

    # Paso 3: Tracking genera el número de seguimiento
    a_compensar = ["inventario", "transportista"]
    try:
        resp = await _post(f"{TRACKING_URL}/generar", {"envio_id": envio_id})
        fallo = None if resp.status_code < 300 else f"Tracking respondió HTTP {resp.status_code}"
    except httpx.RequestError as exc:
        fallo = f"Tracking no responde ({type(exc).__name__})"
        if not isinstance(exc, NO_ENVIADA):
            # La petición salió: el número pudo generarse igual, así que también se anula
            a_compensar.append("tracking")
    if fallo:
        return await _abortar(saga, a_compensar, fallo, 503)
    saga["pasos"].append("tracking")
    saga["codigo_seguimiento"] = resp.json().get("codigo_seguimiento")
    logger.info(f"[{envio_id}] PASO 3 OK tracking generado {saga['codigo_seguimiento']}")

    saga["estado"] = "COMPLETADO"
    logger.info(f"[{envio_id}] SAGA COMPLETADA")
    return saga


@app.get("/envios/{envio_id}")
def consultar_envio(envio_id: str):
    if envio_id not in sagas:
        raise HTTPException(status_code=404, detail="Envío no encontrado")
    return sagas[envio_id]


@app.get("/resiliencia")
def estado_resiliencia():
    # Evidencia: estado del circuito, rechazos del bulkhead y métricas acumuladas
    return protector_transportista.obtener_estado_y_metricas()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5004)
