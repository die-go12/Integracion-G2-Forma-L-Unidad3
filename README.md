# Crear un envío — Encargo integrador Unidad 3 (Forma L, Grupo 2)

Sistema distribuido para la operación **«Crear un envío»** de un operador logístico: Gateway + BFF, Saga con compensaciones y resiliencia sobre la dependencia frágil. Integración de Sistemas, Universidad de Concepción.

## Arquitectura

```
cliente
   │
gateway :8080            único puerto expuesto
   │
  bff
   │
orquestador              Saga «crear envío» + resiliencia
   ├── inventario    + db
   ├── transportista + db   externo y frágil
   └── tracking      + db
```

## Ejecución

```bash
docker compose up --build
curl http://localhost:8080/health
```
