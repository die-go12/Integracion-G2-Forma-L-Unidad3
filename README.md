# Crear un Envío – Encargo Integrador Unidad 3 (Forma L, Grupo 2)

Sistema distribuido para la operación **«Crear un envío»** de un operador logístico.
Integración de Sistemas, Universidad de Concepción.

## Arquitectura

```
Cliente
   │
   ▼
API Gateway :8000          ← Único puerto expuesto
   │  JWT auth + rate-limit
   ▼
BFF (Backend for Frontend) ← Agrega datos, transforma respuestas
   │
   ▼
Orquestador                ← Saga «crear envío» + resiliencia
   ├── Inventario  + DB
   ├── Transportista + DB  (servicio externo y frágil)
   └── Tracking    + DB
```

### Responsabilidades por capa

| Capa | Puerto | Rol |
|---|---|---|
| **API Gateway** | 8000 (público) | Autenticación JWT, rate limiting, proxy al BFF |
| **BFF** | 5005 (interno) | Adaptación de API al cliente, enriquecimiento de respuestas |
| **Orquestador** | 5004 (interno) | Saga con compensaciones, circuit breaker, bulkhead |
| **Inventario** | 5001 (interno) | Gestión de stock y reservas |
| **Transportista** | 5002 (interno) | Agendamiento de retiros (servicio frágil) |
| **Tracking** | 5003 (interno) | Generación de números de seguimiento |

## Ejecución

```bash
docker compose up --build
```

## Uso del API (flujo completo)

### 1. Obtener token JWT

```bash
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "Patricio Estrella", "password": "star123"}'
```

Respuesta:
```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "expires_in": 1800
}
```

### 2. Crear un envío

Inventario arranca con 4 productos de ejemplo. El `producto_id` 1 tiene stock 50, y el 4 tiene
stock 0, útil para probar el rechazo por falta de stock.

```bash
curl -X POST http://localhost:8000/v1/envios \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{"producto_id": 1, "cantidad": 2}'
```

Respuesta exitosa (201):
```json
{
  "envio_id": "ENV-XXXXXXXX",
  "estado": "COMPLETADO",
  "mensaje": "Envío creado exitosamente",
  "codigo_seguimiento": "TRK-XXXXXXXX",
  "codigo_retiro": "RET-XXXXXXXX"
}
```

### 3. Consultar estado de un envío

```bash
curl http://localhost:8000/v1/envios/ENV-XXXXXXXX \
  -H "Authorization: Bearer <JWT>"
```

El BFF agrega tres servicios en una sola respuesta: el estado de la saga (Orquestador),
el retiro (Transportista) y el seguimiento (Tracking). Si Transportista o Tracking no
responden, su campo llega en `null` y el resto de la respuesta se entrega igual.

```json
{
  "envio_id": "ENV-XXXXXXXX",
  "estado": "COMPLETADO",
  "mensaje": "Envío creado exitosamente",
  "codigo_seguimiento": "TRK-XXXXXXXX",
  "codigo_retiro": "RET-XXXXXXXX",
  "pasos_completados": ["inventario", "transportista", "tracking"],
  "retiro": {"envio_id": "ENV-XXXXXXXX", "codigo_retiro": "RET-XXXXXXXX", "estado": "AGENDADO"},
  "seguimiento": {"envio_id": "ENV-XXXXXXXX", "codigo_seguimiento": "TRK-XXXXXXXX", "estado": "CREADO"}
}
```

### 4. Ver métricas de resiliencia

```bash
curl http://localhost:8000/v1/resiliencia \
  -H "Authorization: Bearer <JWT>"
```

## Endpoints del API Gateway

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| `GET`  | `/v1/health`              | No  | Health check del gateway |
| `POST` | `/v1/auth/login`          | No  | Obtener token JWT |
| `POST` | `/v1/envios`              | Sí  | Crear envío (saga completa) |
| `GET`  | `/v1/envios/{envio_id}`   | Sí  | Consultar estado de un envío |
| `GET`  | `/v1/resiliencia`         | Sí  | Métricas de circuit breaker y bulkhead |

## Escenarios de falla

Los comandos están pensados para Git Bash o Linux, con el sistema ya levantado.
Conviene dejar los logs del orquestador abiertos en otra terminal para ver cada paso
de la saga y cada compensación:

```bash
docker compose logs -f orquestador
```

Primero se guarda el token en una variable:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "Patricio Estrella", "password": "star123"}' \
  | sed 's/.*"access_token":"\([^"]*\)".*/\1/')
```

### Escenario 1: camino feliz

```bash
curl -X POST http://localhost:8000/v1/envios \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"producto_id": 1, "cantidad": 2, "envio_id": "DEMO-1"}'
```

Responde 201 con estado `COMPLETADO`. Repetir el mismo comando devuelve el mismo
resultado sin volver a reservar ni agendar (idempotencia por `envio_id`).

### Escenario 2: falla el último paso y se compensa

Se detiene Tracking, que es el paso 3 de la saga:

```bash
docker compose stop tracking

curl -X POST http://localhost:8000/v1/envios \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"producto_id": 1, "cantidad": 2, "envio_id": "DEMO-2"}'
```

Responde 503 con estado `COMPENSADO`. En los logs se ve la compensación en orden
inverso: primero se cancela el retiro en Transportista y después se libera la reserva
en Inventario. Para comprobar que no quedó nada inconsistente:

```bash
# El retiro quedó CANCELADO y las compensaciones aparecen en la respuesta
curl http://localhost:8000/v1/envios/DEMO-2 -H "Authorization: Bearer $TOKEN"

# El stock volvió a su valor anterior y la reserva quedó COMPENSADA
docker compose exec inventario_db psql -U app -d inventario \
  -c "select * from productos" -c "select * from reservas"

docker compose start tracking
```

### Escenario 3: Transportista lento y luego caído

La llamada a Transportista tiene timeout de 2 s, un bulkhead de 3 llamadas simultáneas
y un circuit breaker que se abre al tercer fallo seguido y espera 10 s antes de reintentar.

**Lento, con un pico de 6 envíos simultáneos:**

La forma más simple es el script `pico.py`, que funciona en cualquier terminal
(PowerShell, Git Bash o Linux) y solo usa Python estándar:

```bash
python pico.py
```

El script pone a Transportista lento, lanza los 6 envíos a la vez, manda un envío
más con el circuito abierto, muestra `/v1/resiliencia` y al final deja a
Transportista normal. Cada ejecución usa `envio_id` nuevos, así que se puede
repetir.

También se puede hacer a mano, desde Git Bash o Linux:

```bash
TRANSPORTISTA_LENTO=5 docker compose up -d transportista
sleep 5  # espera a que Transportista termine de arrancar

for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null -w "envio $i: HTTP %{http_code} en %{time_total}s\n" \
    -X POST http://localhost:8000/v1/envios \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"producto_id\": 1, \"cantidad\": 1, \"envio_id\": \"PICO-$i\"}" &
done; wait
```

Tres envíos ocupan el bulkhead y fallan por timeout a los 2 s. Los otros tres se
rechazan de inmediato (`BULKHEAD_SATURADO`) en vez de quedar esperando. Con los tres
timeouts el circuito pasa a `OPEN`, y un envío nuevo falla al instante con
`CIRCUIT_BREAKER_ABIERTO`, sin llamar a Transportista. En todos los casos se responde
con el fallback y la reserva de Inventario se compensa.

```bash
# Estado del circuito y contadores de rechazos
curl http://localhost:8000/v1/resiliencia -H "Authorization: Bearer $TOKEN"
```

**Caído:**

```bash
docker compose stop transportista

curl -X POST http://localhost:8000/v1/envios \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"producto_id": 1, "cantidad": 1, "envio_id": "CAIDO-1"}'
```

Responde 503 con estado `COMPENSADO`. Si el circuito sigue abierto por el paso anterior,
falla al instante (`CIRCUIT_BREAKER_ABIERTO`); si ya se cerró, falla por
`TRANSPORTISTA_CAIDO`. El gateway sigue respondiendo
(`curl http://localhost:8000/v1/health`).

**Recuperación:**

```bash
docker compose up -d transportista
```

Pasados 10 s el circuito deja pasar una llamada de prueba; si resulta bien vuelve a
`CLOSED` y los envíos se completan con normalidad.

Transportista también acepta `TRANSPORTISTA_FALLA=1`, que lo hace responder siempre 500.
