from sqlalchemy import Column, String, DateTime
from datetime import datetime
from database import Base

class Tracking(Base):
    __tablename__ = "trackings"

    id = Column(String, primary_key=True, index=True)
    envio_id = Column(String, unique=True, index=True, nullable=False) # Clave de Idempotencia
    codigo_seguimiento = Column(String, unique=True, nullable=False)
    estado = Column(String, nullable=False, default="CREADO")
    created_at = Column(DateTime, default=datetime.utcnow)