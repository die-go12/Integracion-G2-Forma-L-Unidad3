import os
import bcrypt
from typing import List
from sqlalchemy import create_engine, String, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://postgres:password@localhost:5432/api_db"
)

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

class UserModel(Base):
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[str] = mapped_column(String(20), nullable=False)
    
def _hashear(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def seed_db():
    with SessionLocal() as db:
        if not db.query(UserModel).first():
            seed_users = [
                UserModel(
                    id="11.111.111-1",
                    username="Patricio Estrella",
                    password_hash=_hashear("star123"),
                    rol="admin"
                ),
                UserModel(
                    id="22.222.222-2",
                    username="Bob Esponja",
                    password_hash=_hashear("sponge123"),
                    rol="admin"
                )
            ]
            db.add_all(seed_users)
            db.commit()
        
        
def init_db():
    Base.metadata.create_all(bind=engine)
    seed_db()
    
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()