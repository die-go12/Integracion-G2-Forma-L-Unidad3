"""Servicio Transportista (externo y frágil): agenda y cancela el retiro de un envío.

Es el paso 2 de la Saga «crear envío». Su compensación es /cancelar.

Fallas inducibles por variables de entorno (solo afectan a /agendar):
  TRANSPORTISTA_FALLA=1  -> siempre responde 500
  TRANSPORTISTA_LENTO=3  -> demora 3 segundos antes de responder
"""
import logging
import os
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, String, create_engine, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, declarative_base, sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [transportista] %(message)s")
log = logging.getLogger("transportista")

# --- Fallas inducibles ---
FALLA = os.getenv("TRANSPORTISTA_FALLA", "0") == "1"
LENTO = float(os.getenv("TRANSPORTISTA_LENTO", "0"))

# --- Base de datos ---
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://app:app@transportista_db:5432/transportista",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Retiro(Base):
    __tablename__ = "retiros"

    envio_id = Column(String, primary_key=True)        # clave de idempotencia
    codigo_retiro = Column(String, nullable=True)
    estado = Column(String, nullable=False)            # AGENDADO / CANCELADO
    created_at = Column(DateTime, server_default=func.now())


Base.metadata.create_all(bind=engine)


# --- Esquemas ---
class RetiroRequest(BaseModel):
    envio_id: str


class RetiroResponse(BaseModel):
    envio_id: str
    codigo_retiro: str | None
    estado: str

    class Config:
        from_attributes = True


app = FastAPI(title="transportista")


@app.get("/health")
def health():
    return {"service": "transportista", "status": "ok", "falla": FALLA, "lento": LENTO}


@app.post("/agendar", response_model=RetiroResponse, status_code=status.HTTP_201_CREATED)
def agendar_retiro(req: RetiroRequest, db: Session = Depends(get_db)):
    if LENTO > 0:
        log.info("envio_id=%s respuesta lenta simulada de %ss", req.envio_id, LENTO)
        time.sleep(LENTO)
    if FALLA:
        log.info("envio_id=%s falla simulada", req.envio_id)
        raise HTTPException(status_code=500, detail="Transportista no disponible")

    retiro = db.get(Retiro, req.envio_id)
    if retiro:
        # Si la Saga ya canceló este envío (por ejemplo tras un timeout), no se agenda tarde.
        if retiro.estado == "CANCELADO":
            log.info("envio_id=%s rechazado: el retiro ya fue cancelado", req.envio_id)
            raise HTTPException(status_code=409, detail="El retiro de este envío fue cancelado")
        # Idempotencia: el mismo envío no se agenda dos veces.
        log.info("envio_id=%s ya estaba agendado", req.envio_id)
        return retiro

    retiro = Retiro(
        envio_id=req.envio_id,
        codigo_retiro=f"RET-{uuid.uuid4().hex[:8].upper()}",
        estado="AGENDADO",
    )
    db.add(retiro)
    try:
        db.commit()
    except IntegrityError:
        # Dos peticiones simultáneas del mismo envío: se devuelve la que ganó.
        db.rollback()
        return db.get(Retiro, req.envio_id)
    db.refresh(retiro)
    log.info("envio_id=%s retiro agendado %s", req.envio_id, retiro.codigo_retiro)
    return retiro


@app.post("/cancelar", response_model=RetiroResponse)
def cancelar_retiro(req: RetiroRequest, db: Session = Depends(get_db)):
    """Compensación de la Saga. Es idempotente."""
    retiro = db.get(Retiro, req.envio_id)
    if not retiro:
        # No se llegó a agendar (o sigue en curso): se deja registrada la cancelación
        # para que un /agendar que llegue tarde no deje un retiro huérfano.
        retiro = Retiro(envio_id=req.envio_id, codigo_retiro=None, estado="CANCELADO")
        db.add(retiro)
    else:
        retiro.estado = "CANCELADO"
    db.commit()
    db.refresh(retiro)
    log.info("envio_id=%s retiro cancelado", req.envio_id)
    return retiro
