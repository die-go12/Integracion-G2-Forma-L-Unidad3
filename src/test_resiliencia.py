import asyncio
import time
import threading
from fastapi import FastAPI, HTTPException
import uvicorn

# Ajusta la importación según desde dónde ejecutes el script
from resiliencia.resiliencia import ResilienciaTransportista

# =====================================================================
# 1. MOCK DE TRANSPORTISTA (Simula dependencia externa frágil)
# =====================================================================
mock_app = FastAPI()
estado_mock = {"modo": "NORMAL"}  # Modos: NORMAL, LENTO, CAIDO

@mock_app.post("/agendar")
async def mock_agendar(payload: dict):
    if estado_mock["modo"] == "LENTO":
        await asyncio.sleep(4.0)  # Supera el timeout de 2.0s
    elif estado_mock["modo"] == "CAIDO":
        raise HTTPException(status_code=503, detail="Servicio Transportista no disponible")
    return {"status": "AGENDADO", "envio_id": payload.get("envio_id")}

def iniciar_mock_server():
    uvicorn.run(mock_app, host="127.0.0.1", port=8999, log_level="error")

# =====================================================================
# 2. FALLBACK Y EJECUCIÓN DE PRUEBAS
# =====================================================================
def fallback_prueba(payload: dict, motivo: str) -> dict:
    return {
        "status": "DEGRADADO",
        "motivo": motivo,
        "envio_id": payload.get("envio_id")
    }

async def correr_escenarios():
    # Levantar servidor simulado en segundo plano
    threading.Thread(target=iniciar_mock_server, daemon=True).start()
    await asyncio.sleep(1.0)

    protector = ResilienciaTransportista(
        max_concurrent=2,      # Bulkhead: máximo 2 llamadas simultáneas
        failure_threshold=3,   # Circuit Breaker: abre tras 3 fallos
        recovery_timeout=4.0,  # Espera 4s en OPEN antes de probar HALF_OPEN
        request_timeout=1.5    # Timeout: corta llamadas > 1.5s
    )
    url_mock = "http://127.0.0.1:8999/agendar"

    print("\n--- ESCENARIO A: Camino Feliz (CLOSED) ---")
    estado_mock["modo"] = "NORMAL"
    res = await protector.ejecutar_con_resiliencia(url_mock, {"envio_id": "ENV-1"}, fallback_prueba)
    print("Resultado:", res)

    print("\n--- ESCENARIO B: Prueba de Bulkhead (Concurrencia > max_concurrent) ---")
    estado_mock["modo"] = "LENTO"
    # Lanzamos 4 peticiones simultáneas cuando el límite es 2
    tareas = [
        protector.ejecutar_con_resiliencia(url_mock, {"envio_id": f"ENV-BULK-{i}"}, fallback_prueba)
        for i in range(4)
    ]
    resultados_bulk = await asyncio.gather(*tareas)
    for r in resultados_bulk:
        print("Resultado ráfaga:", r)

    print("\n--- ESCENARIO C: Circuit Breaker OPEN (Fail-Fast) ---")
    # Las 2 que entraron en el paso anterior fallaron por timeout; provocamos el 3er fallo
    estado_mock["modo"] = "CAIDO"
    await protector.ejecutar_con_resiliencia(url_mock, {"envio_id": "ENV-FAIL-3"}, fallback_prueba)
    
    # Esta 4ta llamada debe rechazarse en < 1ms sin tocar el servidor (CIRCUIT_BREAKER_ABIERTO)
    t0 = time.perf_counter()
    res_fast = await protector.ejecutar_con_resiliencia(url_mock, {"envio_id": "ENV-FAST"}, fallback_prueba)
    dt_ms = (time.perf_counter() - t0) * 1000
    print(f"Respuesta Fail-Fast ({dt_ms:.2f} ms):", res_fast)

    print("\n--- ESCENARIO D: Recuperación (HALF_OPEN -> CLOSED) ---")
    print("Esperando 4.2 segundos para que expire recovery_timeout...")
    await asyncio.sleep(4.2)
    estado_mock["modo"] = "NORMAL"
    res_rec = await protector.ejecutar_con_resiliencia(url_mock, {"envio_id": "ENV-REC"}, fallback_prueba)
    print("Resultado recuperación:", res_rec)

    print("\n--- MÉTRICAS FINALES ---")
    print(protector.obtener_estado_y_metricas())

if __name__ == "__main__":
    asyncio.run(correr_escenarios())