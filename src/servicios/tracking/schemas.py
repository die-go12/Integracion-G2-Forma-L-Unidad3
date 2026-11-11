from pydantic import BaseModel

class GenerarTrackingRequest(BaseModel):
    envio_id: str

class TrackingResponse(BaseModel):
    envio_id: str
    codigo_seguimiento: str
    estado: str

    class Config:
        from_attributes = True

class AnularTrackingRequest(BaseModel):
    envio_id: str