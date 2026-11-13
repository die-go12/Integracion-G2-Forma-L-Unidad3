from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uvicorn

# Importaciones locales
from database import engine, Base, get_db
from models import Producto, Reserva
from schemas import CrearProductoRequest, ReservaRequest, CompensacionRequest

# Crea las tablas físicamente en PostgreSQL al iniciar
Base.metadata.create_all(bind=engine)

app = FastAPI(title="inventario")

@app.get("/health")
def health():
    return {"service": "inventario", "status": "ok"}

@app.post("/productos", status_code=status.HTTP_201_CREATED)
def crear_producto(req: CrearProductoRequest, db: Session = Depends(get_db)):
    nuevo_producto = Producto(nombre=req.nombre, stock_disponible=req.stock_inicial)
    db.add(nuevo_producto)
    db.commit()
    db.refresh(nuevo_producto)
    return {"mensaje": "Producto creado", "id": nuevo_producto.id, "stock": nuevo_producto.stock_disponible}

@app.post("/reservar", status_code=status.HTTP_200_OK)
def reservar_inventario(req: ReservaRequest, db: Session = Depends(get_db)):
    reserva_existente = db.query(Reserva).filter(Reserva.saga_id == req.saga_id).first()
    if reserva_existente:
        return {"mensaje": f"Reserva {req.saga_id} ya existía.", "estado": reserva_existente.estado}

    producto = db.query(Producto).filter(Producto.id == req.producto_id).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    if producto.stock_disponible < req.cantidad:
        raise HTTPException(status_code=400, detail="Stock insuficiente")

    producto.stock_disponible -= req.cantidad
    nueva_reserva = Reserva(saga_id=req.saga_id, producto_id=req.producto_id, cantidad=req.cantidad, estado="RESERVADA")
    
    db.add(nueva_reserva)
    db.commit()
    return {"mensaje": "Reserva exitosa", "saga_id": req.saga_id, "stock_restante": producto.stock_disponible}

@app.post("/compensar", status_code=status.HTTP_200_OK)
def compensar_inventario(req: CompensacionRequest, db: Session = Depends(get_db)):
    reserva = db.query(Reserva).filter(Reserva.saga_id == req.saga_id).first()
    if not reserva:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")
    
    if reserva.estado == "COMPENSADA":
        return {"mensaje": "Reserva ya compensada"}
    
    producto = db.query(Producto).filter(Producto.id == reserva.producto_id).first()
    if producto:
        producto.stock_disponible += reserva.cantidad
        
    reserva.estado = "COMPENSADA"
    db.commit()
    return {"mensaje": "Compensación exitosa", "saga_id": req.saga_id}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5001)