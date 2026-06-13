"""Tests for pending file API and consume_pending_file utility."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from app.main import consume_pending_file, pending_files, _guess_content_type


class TestGuessContentType:
    def test_jpg(self):
        assert _guess_content_type("photo.jpg") == "image/jpeg"

    def test_jpeg(self):
        assert _guess_content_type("photo.jpeg") == "image/jpeg"

    def test_png(self):
        assert _guess_content_type("screenshot.png") == "image/png"

    def test_pdf(self):
        assert _guess_content_type("document.pdf") == "application/pdf"

    def test_webp(self):
        assert _guess_content_type("image.webp") == "image/webp"

    def test_txt(self):
        assert _guess_content_type("notes.txt") == "text/plain"

    def test_unknown_extension(self):
        assert _guess_content_type("data.xyz") == "application/octet-stream"

    def test_no_extension(self):
        assert _guess_content_type("README") == "application/octet-stream"

    def test_case_insensitive(self):
        assert _guess_content_type("PHOTO.JPG") == "image/jpeg"


class TestConsumePendingFile:
    def setup_method(self):
        """Clear pending files before each test."""
        pending_files.clear()

    def test_no_pending_file_returns_fallback(self):
        content, filename, ctype = consume_pending_file(b"fallback", "default.txt")
        assert content == b"fallback"
        assert filename == "default.txt"
        assert ctype == "text/plain"

    def test_pending_file_consumed(self, tmp_path):
        test_file = tmp_path / "test_image.jpg"
        test_file.write_bytes(b"\xff\xd8\xff\xe0test image data")
        pending_files["latest"] = str(test_file)

        content, filename, ctype = consume_pending_file(b"fallback", "default.txt")

        assert content == b"\xff\xd8\xff\xe0test image data"
        assert filename == "test_image.jpg"
        assert ctype == "image/jpeg"
        assert "latest" not in pending_files  # consumed and cleared

    def test_pending_file_stale_path_returns_fallback(self):
        pending_files["latest"] = "/nonexistent/path/deleted.jpg"

        content, filename, ctype = consume_pending_file(b"fallback", "default.txt")

        assert content == b"fallback"
        assert filename == "default.txt"
        assert "latest" not in pending_files  # stale entry cleared

    def test_consuming_clears_dict(self, tmp_path):
        test_file = tmp_path / "photo.png"
        test_file.write_bytes(b"png data")
        pending_files["latest"] = str(test_file)

        consume_pending_file(b"", "x.txt")

        assert "latest" not in pending_files

    def test_content_type_from_extension(self, tmp_path):
        test_file = tmp_path / "report.pdf"
        test_file.write_bytes(b"pdf content")
        pending_files["latest"] = str(test_file)

        _, _, ctype = consume_pending_file(b"", "x.txt")
        assert ctype == "application/pdf"


class TestPendingFileEndpoints:
    """Integration tests for the pending file API endpoints."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def setup_method(self):
        pending_files.clear()

    def test_get_pending_file_empty(self, client):
        resp = client.get("/api/pending-file")
        assert resp.status_code == 200
        assert resp.json()["has_file"] is False

    def test_upload_and_get_pending_file(self, client):
        resp = client.post(
            "/api/pending-file",
            files={"file": ("test.jpg", b"image data", "image/jpeg")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test.jpg"
        assert "file_path" not in data  # no server path leaked
        assert data["content_type"] == "image/jpeg"

        # Check it's available
        get_resp = client.get("/api/pending-file")
        assert get_resp.json()["has_file"] is True

    def test_delete_pending_file(self, client):
        client.post(
            "/api/pending-file",
            files={"file": ("test.jpg", b"data", "image/jpeg")},
        )
        del_resp = client.delete("/api/pending-file")
        assert del_resp.status_code == 200

        get_resp = client.get("/api/pending-file")
        assert get_resp.json()["has_file"] is False

    def test_upload_replaces_previous(self, client):
        client.post("/api/pending-file", files={"file": ("a.jpg", b"a", "image/jpeg")})
        client.post("/api/pending-file", files={"file": ("b.png", b"b", "image/png")})

        get_resp = client.get("/api/pending-file")
        assert get_resp.json()["has_file"] is True
        # Only the latest file should be stored (filename has UUID prefix)
        assert get_resp.json()["filename"].endswith("b.png")

    def test_get_response_does_not_leak_file_path(self, client):
        client.post("/api/pending-file", files={"file": ("x.jpg", b"x", "image/jpeg")})
        resp = client.get("/api/pending-file")
        data = resp.json()
        assert "file_path" not in data or not data.get("file_path", "").startswith("/")
