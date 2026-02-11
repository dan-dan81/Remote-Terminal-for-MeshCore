import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.frontend_static import register_frontend_static_routes


def test_missing_dist_logs_error_and_keeps_app_running(tmp_path, caplog):
    app = FastAPI()
    missing_dist = tmp_path / "frontend" / "dist"

    with caplog.at_level(logging.ERROR):
        registered = register_frontend_static_routes(app, missing_dist)

    assert registered is False
    assert "Frontend build directory not found" in caplog.text

    with TestClient(app) as client:
        # App still runs; no frontend route is registered.
        assert client.get("/").status_code == 404


def test_missing_index_logs_error_and_skips_frontend_routes(tmp_path, caplog):
    app = FastAPI()
    dist_dir = tmp_path / "frontend" / "dist"
    dist_dir.mkdir(parents=True)

    with caplog.at_level(logging.ERROR):
        registered = register_frontend_static_routes(app, dist_dir)

    assert registered is False
    assert "Frontend index file not found" in caplog.text


def test_valid_dist_serves_static_and_spa_fallback(tmp_path):
    app = FastAPI()
    dist_dir = tmp_path / "frontend" / "dist"
    assets_dir = dist_dir / "assets"
    dist_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)

    index_file = dist_dir / "index.html"
    index_file.write_text("<html><body>index page</body></html>")
    (dist_dir / "robots.txt").write_text("User-agent: *")
    (assets_dir / "app.js").write_text("console.log('ok');")

    registered = register_frontend_static_routes(app, dist_dir)
    assert registered is True

    with TestClient(app) as client:
        root_response = client.get("/")
        assert root_response.status_code == 200
        assert "index page" in root_response.text

        file_response = client.get("/robots.txt")
        assert file_response.status_code == 200
        assert file_response.text == "User-agent: *"

        missing_response = client.get("/channel/some-route")
        assert missing_response.status_code == 200
        assert "index page" in missing_response.text

        asset_response = client.get("/assets/app.js")
        assert asset_response.status_code == 200
        assert "console.log('ok');" in asset_response.text
