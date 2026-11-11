import os
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# 1. Configuración global
SECRET_KEY = os.getenv("SECRET_KEY", "CLAVE_DESARROLLO")
ALGORITHM = "HS256"
MINUTOS_EXPIRACION = 30

_bearer = HTTPBearer(auto_error=False)

# 2. Hashing de contraseñas
def hashear_password(password : str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verificat_password(password : str, password_hash : str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

# 3. Emisión de tokens JWT
def crear_token(username: str, rol: str) -> str:
    expira = datetime.now(timezone.utc) + timedelta(minutes=MINUTOS_EXPIRACION)
    payload = {
        "sub": username,
        "rol": rol,
        "exp": expira
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

# 4. Dependencia de seguridad para validar el Token en los endpoints
def obtener_usuario_actual(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> dict:
    if not credenciales:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"codigo": "ERR_401", "mensaje": "Falta token de autenticación."},
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    token = credenciales.credentials
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"username": payload.get("sub"), "rol": payload.get("rol")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"codigo": "ERR_401", "mensaje": "El token ha expirado."},
            headers={"WWW-Authenticate": "Bearer"} 
        )
        
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"codigo": "ERR_401", "mensaje": "Token invalidado"},
            headers={"WWW-Authenticate": "Bearer"}
        )