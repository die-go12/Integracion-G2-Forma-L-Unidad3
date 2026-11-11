"""BFF: aggregates data from several services into one client-shaped response."""
from fastapi import FastAPI

app = FastAPI(title="bff")


@app.get("/health")
def health():
    return {"service": "bff", "status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5005)
