import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models import Producto, Reserva


# Rescatamos las variables de entorno de Docker
DB_USER = os.getenv("POSTGRES_USER", "app")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "app")
DB_HOST = os.getenv("DB_HOST", "inventario_db")
DB_NAME = os.getenv("POSTGRES_DB", "inventario")

DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        
def seed_db():
    with SessionLocal() as db:
        if not db.query(Producto).first():
            db.add_all([
                Producto(id=1, nombre="Laptop Lenovo ThinkPad", stock_disponible=50),
                Producto(id=2, nombre="Monitor Dell 27\"", stock_disponible=30),
                Producto(id=3, nombre="Teclado Mecanico", stock_disponible=100),
                Producto(id=4, nombre="Producto Sin Stock", stock_disponible=0),
            ])
            db.flush()
            db.execute(text(
                "SELECT setval(pg_get_serial_sequence('productos', 'id'), COALESCE(MAX(id), 1)) FROM productos"
            ))

        if not db.query(Reserva).first():
            db.add_all([
                Reserva(saga_id="ENV-SEED-001", producto_id=1, cantidad=2, estado="RESERVADA"),
                Reserva(saga_id="ENV-SEED-002", producto_id=2, cantidad=1, estado="COMPENSADA"),
            ])

        db.commit()