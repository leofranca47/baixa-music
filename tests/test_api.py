import os
import tempfile
from unittest.mock import patch, AsyncMock, MagicMock
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.downloader import DownloadResult, download_audio, cleanup_task_files

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

@pytest.mark.anyio
async def test_download_audio_restores_backup_when_overwritten(tmp_path, monkeypatch):
    # Um canal externo sobrescreve o cookies.txt com export sem login:
    # a conversão deve restaurar o último upload validado automaticamente.
    destino = tmp_path / "cookies.txt"
    validos = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tSID\tabc123\n"
    )
    destino.write_text(".youtube.com\tTRUE\t/\tTRUE\t9999999999\tPREF\tvisitor\n", encoding="utf-8")
    (tmp_path / "cookies.txt.valido").write_text(validos, encoding="utf-8")
    monkeypatch.setattr("app.downloader.YTDLP_COOKIES_FILE", str(destino))

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        async def side_effect(*cmd, **kwargs):
            for i, arg in enumerate(cmd):
                if arg == "-o":
                    out_dir = os.path.dirname(cmd[i + 1])
                    with open(os.path.join(out_dir, "My Song.mp3"), "wb") as f:
                        f.write(b"data")
                    break
            return fake_proc

        mock_exec.side_effect = side_effect

        result = await download_audio("https://www.youtube.com/watch?v=123", "mp3", "task-restore")

        # O arquivo atual foi restaurado com o conteúdo validado
        assert destino.read_text(encoding="utf-8") == validos
        # E a flag --cookies continua sendo passada
        cmd = list(mock_exec.call_args[0])
        assert "--cookies" in cmd
        cleanup_task_files(result.temp_dir)

@pytest.mark.anyio
async def test_download_audio_keeps_broken_file_without_backup(tmp_path, monkeypatch):
    # Sem backup válido o arquivo quebrado permanece (nada para restaurar).
    destino = tmp_path / "cookies.txt"
    destino.write_text(".youtube.com\tTRUE\t/\tTRUE\t9999999999\tPREF\tvisitor\n", encoding="utf-8")
    monkeypatch.setattr("app.downloader.YTDLP_COOKIES_FILE", str(destino))

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        async def side_effect(*cmd, **kwargs):
            for i, arg in enumerate(cmd):
                if arg == "-o":
                    out_dir = os.path.dirname(cmd[i + 1])
                    with open(os.path.join(out_dir, "My Song.mp3"), "wb") as f:
                        f.write(b"data")
                    break
            return fake_proc

        mock_exec.side_effect = side_effect

        result = await download_audio("https://www.youtube.com/watch?v=123", "mp3", "task-keep")
        assert "PREF" in destino.read_text(encoding="utf-8")
        cleanup_task_files(result.temp_dir)
