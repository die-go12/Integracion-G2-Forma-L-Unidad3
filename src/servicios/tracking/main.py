import uuid
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import uvicorn

from database import engine, get_db, seed_db
import models
import schemas

models.Base.metadata.create_all(bind=engine)

seed_db()

app = FastAPI(title="tracking")


@app.get("/health")
def health():
    return {"service": "tracking", "status": "ok"}


@app.get("/trackings", response_model=list[schemas.TrackingResponse])
def listar_trackings(db: Session = Depends(get_db)):
    return db.query(models.Tracking).all()


@app.post("/generar", response_model=schemas.TrackingResponse, status_code=status.HTTP_201_CREATED)
def generar_tracking(req: schemas.GenerarTrackingRequest, db: Session = Depends(get_db)):
    # 1. Idempotencia: si ya existe el envio_id, retorna el mismo registro
    tracking_existente = (
        db.query(models.Tracking)
        .filter(models.Tracking.envio_id == req.envio_id)
        .first()
    )
    if tracking_existente:
        return tracking_existente

    # 2. Creación de nuevo tracking
    nuevo_tracking = models.Tracking(
        id=str(uuid.uuid4()),
        envio_id=req.envio_id,
        codigo_seguimiento=f"TRK-{uuid.uuid4().hex[:8].upper()}",
        estado="CREADO"
    )
    db.add(nuevo_tracking)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return (
            db.query(models.Tracking)
            .filter(models.Tracking.envio_id == req.envio_id)
            .first()
        )
    db.refresh(nuevo_tracking)
    return nuevo_tracking


@app.post("/anular", response_model=schemas.TrackingResponse)
def anular_tracking(req: schemas.AnularTrackingRequest, db: Session = Depends(get_db)):
    tracking = (
        db.query(models.Tracking)
        .filter(models.Tracking.envio_id == req.envio_id)
        .first()
    )

    if not tracking:
        raise HTTPException(status_code=404, detail="Tracking no encontrado para anulación")

    # Idempotencia en compensación: si ya estaba ANULADO, retorna directo sin re-escribir
    if tracking.estado == "ANULADO":
        return tracking

    tracking.estado = "ANULADO"
    db.commit()
    db.refresh(tracking)
    return tracking


@app.get("/tracking/{envio_id}", response_model=schemas.TrackingResponse)
def consultar_tracking(envio_id: str, db: Session = Depends(get_db)):
    # Consulta de solo lectura (la usa el BFF)
    tracking = (
        db.query(models.Tracking)
        .filter(models.Tracking.envio_id == envio_id)
        .first()
    )
    if not tracking:
        raise HTTPException(status_code=404, detail="Tracking no encontrado")
    return tracking


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5003)