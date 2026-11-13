from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,     # Obtiene la dirección IP
    default_limits=["60/minute"],    # Límite global por defecto: 60 peticiones por minuto
    storage_uri="memory://"          # Almacenamiento local
)