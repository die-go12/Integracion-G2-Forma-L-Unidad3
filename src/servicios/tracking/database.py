import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import models

DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://tracking_user:tracking_password@tracking-db:5432/tracking_db"
)

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
        if not db.query(models.Tracking).first():
            db.add_all([
                models.Tracking(
                    id="00000000-0000-0000-0000-000000000001",
                    envio_id="ENV-SEED-001",
                    codigo_seguimiento="TRK-SEED0001",
                    estado="CREADO",
                ),
                models.Tracking(
                    id="00000000-0000-0000-0000-000000000002",
                    envio_id="ENV-SEED-002",
                    codigo_seguimiento="TRK-SEED0002",
                    estado="ANULADO",
                ),
            ])
            db.commit()