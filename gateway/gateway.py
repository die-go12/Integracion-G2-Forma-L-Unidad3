"""API Gateway: single entry point (routing, token auth, rate limiting)."""
from fastapi import FastAPI

app = FastAPI(title="gateway")


@app.get("/health")
def health():
    return {"service": "gateway", "status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
