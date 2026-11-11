"""API Gateway: single entry point (routing, token auth, rate limiting)."""
from fastapi import FastAPI
from pydantic import BaseModel
from database import init_db, get_db
import uvicorn

app = FastAPI(title="gateway")

# Esquemas
class LoginInput(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


@app.get("/v1/health")
def health():
    return {"service": "gateway", "status": "ok"}

@app.post("/v1/auth/login", response_model=LoginResponse)
def login(credentials: LoginInput):
    pass

if __name__ == "__main__":
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=8080)
