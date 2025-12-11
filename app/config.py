import os
import logging
import sys
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App
    APP_NAME: str = "PDF Editor API"
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"  # Set to DEBUG to see detailed coordinate/detection logs

    # Database
    DATABASE_URL: str = "sqlite:///./pdf_editor.db"

    # File Storage
    UPLOAD_DIR: str = "./uploads"
    GENERATED_DIR: str = "./generated"

    # OCR
    TESSERACT_CMD: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://127.0.0.1:5500"

    # Limits
    MAX_FILE_SIZE_MB: int = 50

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    def ensure_directories(self):
        """Create upload and generated directories if they don't exist."""
        Path(self.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.GENERATED_DIR).mkdir(parents=True, exist_ok=True)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure application logging."""
    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)

    # Create application logger
    app_logger = logging.getLogger("pdf_editor")
    app_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    return app_logger


# Global settings instance
settings = Settings()
settings.ensure_directories()

# Setup logging
logger = setup_logging(settings.LOG_LEVEL)
