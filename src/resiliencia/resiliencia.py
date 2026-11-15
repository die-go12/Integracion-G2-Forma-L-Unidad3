"""Resilience patterns used by the orchestrator: timeout, circuit breaker, bulkhead."""

import asyncio
import time
import logging
from enum import Enum
from typing import Callable, Any, Dict
import httpx

# Configuración de logging estructurado para evidencia en consola
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [RESILIENCIA] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("resiliencia")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # Funcionamiento normal
    OPEN = "OPEN"            # Circuito abierto: fail-fast directo al fallback
    HALF_OPEN = "HALF_OPEN"  # Prueba controlada de recuperación


class BulkheadFullException(Exception):
    # cuando se agota el pool de concurrencia asignado al servicio
    pass


class CircuitOpenException(Exception):
    """Se lanza cuando el circuito está abierto y bloquea la llamada."""
    pass


class ResilienciaTransportista:
    def __init__(
        self,
        max_concurrent: int = 3,        # límite del Bulkhead
        failure_threshold: int = 3,     # fallos para abrir el Circuit Breaker
        recovery_timeout: float = 10.0, # segundos en OPEN antes de probar HALF_OPEN
        request_timeout: float = 2.0    # timeout por llamada HTTP 
    ):
        # 1. Bulkhead: Semáforo de concurrencia
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_calls = 0

        # 2. Circuit Breaker: Máquina de estados
        self.state = CircuitState.CLOSED
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0.0

        # 3. Timeout
        self.request_timeout = request_timeout

        # 4. Métricas acumuladas 
        self.metrics: Dict[str, int] = {
            "total_requests": 0,
            "successful_calls": 0,
            "timeouts_or_errors": 0,
            "circuit_open_rejections": 0,
            "bulkhead_rejections": 0,
            "fallback_executions": 0
        }

    def _can_attempt_call(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.warning(
                    f"Circuit Breaker transición: OPEN -> HALF_OPEN (tras {elapsed:.1f}s). Probando recuperación..."
                )
                return True
            return False

        # en HALF_OPEN se permite pasar la petición de prueba
        return True

    def _record_success(self):
        # Registra una llamada exitosa y cierra el circuito si estaba en prueba
        self.metrics["successful_calls"] += 1
        if self.state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
            logger.info(f"Circuit Breaker transición: {self.state.value} -> CLOSED. Servicio recuperado.")
        self.state = CircuitState.CLOSED
        self.failure_count = 0

    def _record_failure(self, reason: str):
        # Registra un fallo/timeout y abre el circuito si alcanza el umbral
        self.metrics["timeouts_or_errors"] += 1
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        logger.error(
            f"Fallo en Transportista ({reason}). Fallos consecutivos: {self.failure_count}/{self.failure_threshold}"
        )

        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                logger.critical(
                    f"Circuit Breaker transición: {self.state.value} -> OPEN. "
                    f"Activando fail-fast por {self.recovery_timeout}s."
                )
            self.state = CircuitState.OPEN

    async def ejecutar_con_resiliencia(
        self,
        url: str,
        payload: dict,
        fallback_fn: Callable[[dict, str], Any]
    ) -> Any:
        """
        Envuelve la llamada HTTP POST hacia Transportista aplicando:
        Bulkhead -> Circuit Breaker -> Timeout -> Fallback.
        """
        self.metrics["total_requests"] += 1
        start_time = time.perf_counter()

        # bulkhead
        if self._semaphore.locked():
            self.metrics["bulkhead_rejections"] += 1
            self.metrics["fallback_executions"] += 1
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                f"[BULKHEAD REJECT] Pool saturado ({self._active_calls}/{self.max_concurrent} en uso). "
                f"Rechazado en {elapsed_ms:.2f}ms."
            )
            return fallback_fn(payload, "BULKHEAD_SATURADO")

        async with self._semaphore:
            self._active_calls += 1
            try:
                # circuit breaker
                if not self._can_attempt_call():
                    self.metrics["circuit_open_rejections"] += 1
                    self.metrics["fallback_executions"] += 1
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    logger.warning(
                        f"[CIRCUIT OPEN - FAIL FAST] Llamada bloqueada inmediatamente en {elapsed_ms:.2f}ms."
                    )
                    return fallback_fn(payload, "CIRCUIT_BREAKER_ABIERTO")

                # timeout y llamada
                async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    
                    self._record_success()
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    logger.info(f"Llamada exitosa a Transportista en {elapsed_ms:.2f}ms.")
                    return response.json()

            except httpx.TimeoutException:
                self._record_failure(f"TIMEOUT > {self.request_timeout}s")
                self.metrics["fallback_executions"] += 1
                return fallback_fn(payload, "TIMEOUT_TRANSPORTISTA")

            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                self._record_failure(f"ERROR_RED_O_HTTP: {type(exc).__name__}")
                self.metrics["fallback_executions"] += 1
                return fallback_fn(payload, "TRANSPORTISTA_CAIDO")

            finally:
                self._active_calls -= 1

    def obtener_estado_y_metricas(self) -> dict:
        # evidencias 
        return {
            "circuit_state": self.state.value,
            "failure_count": self.failure_count,
            "bulkhead_active": self._active_calls,
            "bulkhead_max": self.max_concurrent,
            "metrics": self.metrics
        }