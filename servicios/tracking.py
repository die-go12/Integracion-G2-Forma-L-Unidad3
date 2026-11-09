"""Tracking: generates and voids the tracking number."""
from fastapi import FastAPI

app = FastAPI(title="tracking")


@app.get("/health")
def health():
    return {"service": "tracking", "status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5003)
