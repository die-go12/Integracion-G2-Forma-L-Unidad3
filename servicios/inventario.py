"""Inventario: reserves and releases the goods of a shipment."""
from fastapi import FastAPI

app = FastAPI(title="inventario")


@app.get("/health")
def health():
    return {"service": "inventario", "status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5001)
