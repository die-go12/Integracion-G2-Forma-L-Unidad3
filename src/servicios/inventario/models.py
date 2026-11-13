from sqlalchemy import Column, Integer, String
from database import Base

class Producto(Base):
    __tablename__ = "productos"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, index=True)
    stock_disponible = Column(Integer, nullable=False)

class Reserva(Base):
    __tablename__ = "reservas"
    
    saga_id = Column(String, primary_key=True, index=True) 
    producto_id = Column(Integer, nullable=False)
    cantidad = Column(Integer, nullable=False)
    estado = Column(String, nullable=False)