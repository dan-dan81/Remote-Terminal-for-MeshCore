import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)


def register_frontend_static_routes(app: FastAPI, frontend_dir: Path) -> bool:
    """Register frontend static file routes if a built frontend is available.

    Returns True when routes are registered, False when frontend files are
    missing/incomplete. Missing frontend files are logged but are not fatal.
    """
    frontend_dir = frontend_dir.resolve()
    index_file = frontend_dir / "index.html"
    assets_dir = frontend_dir / "assets"

    if not frontend_dir.exists():
        logger.error(
            "Frontend build directory not found at %s. "
            "Run 'cd frontend && npm run build'. API will continue without frontend routes.",
            frontend_dir,
        )
        return False

    if not frontend_dir.is_dir():
        logger.error(
            "Frontend build path is not a directory: %s. "
            "API will continue without frontend routes.",
            frontend_dir,
        )
        return False

    if not index_file.exists():
        logger.error(
            "Frontend index file not found at %s. "
            "Run 'cd frontend && npm run build'. API will continue without frontend routes.",
            index_file,
        )
        return False

    if assets_dir.exists() and assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    else:
        logger.warning(
            "Frontend assets directory missing at %s; /assets files will not be served",
            assets_dir,
        )

    @app.get("/")
    async def serve_index():
        """Serve the frontend index.html."""
        return FileResponse(index_file)

    @app.get("/{path:path}")
    async def serve_frontend(path: str):
        """Serve frontend files, falling back to index.html for SPA routing."""
        file_path = (frontend_dir / path).resolve()
        try:
            file_path.relative_to(frontend_dir)
        except ValueError:
            raise HTTPException(status_code=404, detail="Not found") from None

        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)

        return FileResponse(index_file)

    logger.info("Serving frontend from %s", frontend_dir)
    return True
