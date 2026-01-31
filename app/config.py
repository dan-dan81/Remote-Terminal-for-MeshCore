import logging
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MESHCORE_")

    serial_port: str = ""  # Empty string triggers auto-detection
    serial_baudrate: int = 115200
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_path: str = "data/meshcore.db"


settings = Settings()


def setup_logging() -> None:
    """Configure logging for the application."""
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
