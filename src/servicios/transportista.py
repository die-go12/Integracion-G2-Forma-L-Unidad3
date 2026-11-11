"""Transportista (external, fragile): schedules and cancels the pickup."""
from fastapi import FastAPI

app = FastAPI(title="transportista")


@app.get("/health")
def health():
    return {"service": "transportista", "status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5002)
