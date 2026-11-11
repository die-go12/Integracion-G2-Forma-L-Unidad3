import os
import uuid
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import uvicorn

# --- Configuración de Base de Datos ---
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "sqlite:///./tracking.db"
)

engine_kwargs = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class TrackingModel(Base):
    __tablename__ = "trackings"

    id = Column(String, primary_key=True, index=True)
    envio_id = Column(String, unique=True, index=True, nullable=False)  # Clave de Idempotencia
    codigo_seguimiento = Column(String, unique=True, nullable=False)
    estado = Column(String, nullable=False, default="CREADO")            # CREADO / ANULADO
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

class GenerarTrackingRequest(BaseModel):
    envio_id: str

class AnularTrackingRequest(BaseModel):
    envio_id: str

class TrackingResponse(BaseModel):
    envio_id: str
    codigo_seguimiento: str
    estado: str

    class Config:
        from_attributes = True


app = FastAPI(title="tracking")

@app.get("/health")
def health():
    return {"service": "tracking", "status": "ok"}

@app.post("/generar", response_model=TrackingResponse, status_code=status.HTTP_201_CREATED)
def generar_tracking(req: GenerarTrackingRequest, db: Session = Depends(get_db)):
    # 1. Comprobar Idempotencia: Si el envio_id ya existe, devolver el registro previo
    tracking_existente = db.query(TrackingModel).filter(TrackingModel.envio_id == req.envio_id).first()
    if tracking_existente:
        return tracking_existente

    # 2. Si no existe, generar nuevo código de seguimiento
    nuevo_codigo = f"TRK-{uuid.uuid4().hex[:8].upper()}"
    nuevo_tracking = TrackingModel(
        id=str(uuid.uuid4()),
        envio_id=req.envio_id,
        codigo_seguimiento=nuevo_codigo,
        estado="CREADO"
    )
    
    db.add(nuevo_tracking)
    db.commit()
    db.refresh(nuevo_tracking)
    return nuevo_tracking

@app.post("/anular", response_model=TrackingResponse)
def anular_tracking(req: AnularTrackingRequest, db: Session = Depends(get_db)):
    # Compensación de la Saga: Anular el tracking asociado al envio_id
    tracking = db.query(TrackingModel).filter(TrackingModel.envio_id == req.envio_id).first()
    
    if not tracking:
        raise HTTPException(status_code=404, detail="Tracking no encontrado para anulación")

    tracking.estado = "ANULADO"
    db.commit()
    db.refresh(tracking)
    return tracking

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5003)