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

## Simular fallas del Transportista

```bash
# Falla total
TRANSPORTISTA_FALLA=1 docker compose up --build

# Respuesta lenta (provoca timeout)
TRANSPORTISTA_LENTO=3 docker compose up --build
```
