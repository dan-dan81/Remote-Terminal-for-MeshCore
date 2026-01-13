import os

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.radio import radio_manager


router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    radio_connected: bool
    serial_port: str | None
    database_size_mb: float


@router.get("/health", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    """Check if the API is running and if the radio is connected."""
    # Get database file size in MB
    db_size_mb = 0.0
    try:
        db_size_bytes = os.path.getsize(settings.database_path)
        db_size_mb = round(db_size_bytes / (1024 * 1024), 2)
    except OSError:
        pass

    return HealthResponse(
        status="ok" if radio_manager.is_connected else "degraded",
        radio_connected=radio_manager.is_connected,
        serial_port=radio_manager.port,
        database_size_mb=db_size_mb,
    )
