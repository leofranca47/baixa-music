import os
import tempfile
from unittest.mock import patch, AsyncMock
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.downloader import DownloadResult

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.anyio
async def test_get_root_serves_html():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "Baixa YouTube" in response.text

@pytest.mark.anyio
async def test_convert_invalid_payload():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Invalid format
        response = await client.post("/api/convert", json={"url": "https://youtube.com/watch?v=123", "format": "exe"})
        assert response.status_code in (400, 422)

        # Missing URL
        response = await client.post("/api/convert", json={"format": "mp3"})
        assert response.status_code == 422

        # Invalid URL schema
        response = await client.post("/api/convert", json={"url": "not-a-valid-url", "format": "mp3"})
        assert response.status_code in (400, 422)

@pytest.mark.anyio
async def test_convert_success():
    fake_temp_dir = tempfile.mkdtemp()
    fake_file = os.path.join(fake_temp_dir, "test_audio.mp3")
    with open(fake_file, "wb") as f:
        f.write(b"ID3fakeaudiodata")

    mock_result = DownloadResult(
        task_id="test-task-123",
        title="Test Song",
        file_path=fake_file,
        format="mp3",
        temp_dir=fake_temp_dir
    )

    with patch("app.main.download_audio", new_callable=AsyncMock) as mock_download:
        mock_download.return_value = mock_result
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/convert", json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "format": "mp3"
            })
            assert response.status_code == 200
            data = response.json()
            assert data["task_id"] == "test-task-123"
            assert data["title"] == "Test Song"
            assert data["format"] == "mp3"
            assert data["download_url"] == "/api/download/test-task-123"

@pytest.mark.anyio
async def test_download_file_and_cleanup():
    fake_temp_dir = tempfile.mkdtemp()
    fake_file = os.path.join(fake_temp_dir, "test_audio.mp3")
    with open(fake_file, "wb") as f:
        f.write(b"ID3fakeaudiodata")

    # Register task directly in app storage for the test
    from app.main import active_downloads
    task_id = "download-test-task"
    active_downloads[task_id] = {
        "file_path": fake_file,
        "filename": "Test Song.mp3",
        "format": "mp3",
        "temp_dir": fake_temp_dir
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/download/{task_id}")
        assert response.status_code == 200
        assert response.content == b"ID3fakeaudiodata"
        cd_header = response.headers.get("content-disposition", "")
        assert cd_header.startswith("attachment;")
        assert "Test" in cd_header and "mp3" in cd_header

    # Check cleanup occurred (File and temp_dir removed)
    assert not os.path.exists(fake_file)
    assert not os.path.exists(fake_temp_dir)
    assert task_id not in active_downloads

@pytest.mark.anyio
async def test_convert_yt_dlp_failure():
    from app.downloader import DownloaderError
    with patch("app.main.download_audio", new_callable=AsyncMock) as mock_download:
        mock_download.side_effect = DownloaderError("Video unavailable: Incomplete YouTube ID")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/convert", json={
                "url": "https://www.youtube.com/watch?v=invalid",
                "format": "mp3"
            })
            assert response.status_code == 422
            data = response.json()
            assert "Erro ao processar áudio" in data["detail"]
            assert "Video unavailable" in data["detail"]

@pytest.mark.anyio
async def test_download_not_found():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/download/non-existent-id")
        assert response.status_code == 404

@pytest.mark.anyio
async def test_upload_cookies_valid_saves_file(monkeypatch, tmp_path):
    destino = tmp_path / "cookies.txt"
    monkeypatch.setattr("app.downloader.YTDLP_COOKIES_FILE", str(destino))
    conteudo = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tSID\tabc123\n"
        ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tLOGIN_INFO\txyz\n"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/cookies",
            files={"file": ("cookies.txt", conteudo.encode("utf-8"), "text/plain")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["cookies"] == 2
        assert "Sessão logada" in data["mensagem"]
    assert destino.read_text(encoding="utf-8") == conteudo
    assert not os.path.exists(str(destino) + ".tmp")

@pytest.mark.anyio
async def test_upload_cookies_without_login_is_rejected(monkeypatch, tmp_path):
    destino = tmp_path / "cookies.txt"
    destino.write_text("ORIGINAL\n", encoding="utf-8")
    monkeypatch.setattr("app.downloader.YTDLP_COOKIES_FILE", str(destino))
    conteudo = ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tPREF\tvisitor\n"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/cookies",
            files={"file": ("cookies.txt", conteudo.encode("utf-8"), "text/plain")},
        )
        assert response.status_code == 422
        assert "NENHUM de sessão logada" in response.json()["detail"]
    # Export sem login não pode sobrescrever o arquivo atual
    assert destino.read_text(encoding="utf-8") == "ORIGINAL\n"

@pytest.mark.anyio
async def test_upload_cookies_invalid_format(monkeypatch, tmp_path):
    destino = tmp_path / "cookies.txt"
    monkeypatch.setattr("app.downloader.YTDLP_COOKIES_FILE", str(destino))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/cookies",
            files={"file": ("cookies.txt", b"qualquer coisa aleatoria", "text/plain")},
        )
        assert response.status_code == 422
    assert not destino.exists()
