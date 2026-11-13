from pydantic import BaseModel

class CrearProductoRequest(BaseModel):
    nombre: str
    stock_inicial: int

class ReservaRequest(BaseModel):
    saga_id: str
    producto_id: int
    cantidad: int

class CompensacionRequest(BaseModel):
    saga_id: str