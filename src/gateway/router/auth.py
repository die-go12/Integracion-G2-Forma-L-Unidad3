from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from database import get_db, UserModel
from auth import verificar_password, crear_token, MINUTOS_EXPIRACION
from limiter import limiter

router = APIRouter(prefix="/v1/auth", tags=["Autenticación"])

# Esquemas
class LoginInput(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    
@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login(request: Request, data: LoginInput, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.username == data.username).first()
    
    if not user or not verificar_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"codigo": "ERR_401", "mensaje": "Usuario o contraseña incorrectos."},
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    token = crear_token(username=user.username, rol=user.rol)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": MINUTOS_EXPIRACION*60
    }