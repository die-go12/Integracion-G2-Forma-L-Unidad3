"""Saga orchestrator for 'crear envio': runs the steps and compensates in reverse order."""
from fastapi import FastAPI
from resiliencia.resiliencia import ResilienciaTransportista

# Instancia global compartida por todas las peticiones del orquestador
protector_transportista = ResilienciaTransportista(
    max_concurrent=3,      # Máximo 3 llamadas simultáneas a Transportista
    failure_threshold=3,   # Al 3er fallo consecutivo se abre el circuito
    recovery_timeout=10.0, # Se mantiene abierto 10 segundos antes de probar
    request_timeout=2.0    # Máximo 2 segundos de espera por petición
)

def fallback_agendar_retiro(payload: dict, motivo: str) -> dict:
    # degradación cuando Transportista falla o está saturado
    # permite que el envío quede registrado como PENDIENTE_RETIRO en lugar de
    # bloquear o botar todo el sistema.
    return {
        "status": "DEGRADADO",
        "agendado": False,
        "estado_retiro": "PENDIENTE_RETIRO_DIFERIDO",
        "motivo_fallback": motivo,
        "envio_id": payload.get("envio_id")
    }

app = FastAPI(title="orquestador")


@app.get("/health")
def health():
    return {"service": "orquestador", "status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5004)
