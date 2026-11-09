"""Saga orchestrator for 'crear envio': runs the steps and compensates in reverse order."""
from fastapi import FastAPI

app = FastAPI(title="orquestador")


@app.get("/health")
def health():
    return {"service": "orquestador", "status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5004)
