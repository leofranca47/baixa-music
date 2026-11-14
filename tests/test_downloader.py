import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.downloader import download_audio, cleanup_task_files, DownloaderError

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.anyio
async def test_download_audio_success(tmp_path):
    # Mock subprocess communicate returning exit code 0 and creating a fake file in temp_dir
    fake_proc = MagicMock()
    fake_proc.returncode = 0

    async def fake_communicate():
        # Find the temp dir created inside /tmp
        # We can simulate file creation in any dir
        return b"", b""

    fake_proc.communicate = fake_communicate

    # When create_subprocess_exec is called, we populate the temp dir created
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = fake_proc

        async def side_effect(*cmd, **kwargs):
            # Find the -o path in cmd
            for i, arg in enumerate(cmd):
                if arg == "-o":
                    out_pattern = cmd[i + 1]
                    out_dir = os.path.dirname(out_pattern)
                    # create audio file
                    with open(os.path.join(out_dir, "My Song.mp3"), "wb") as f:
                        f.write(b"data")
                    break
            return fake_proc

        mock_exec.side_effect = side_effect

        result = await download_audio("https://www.youtube.com/watch?v=123", "mp3", "task-999")
        assert result.task_id == "task-999"
        assert result.title == "My Song"
        assert result.format == "mp3"
        assert os.path.exists(result.file_path)

        # Cleanup
        cleanup_task_files(result.temp_dir)
        assert not os.path.exists(result.temp_dir)

@pytest.mark.anyio
async def test_download_audio_process_failure():
    fake_proc = MagicMock()
    fake_proc.returncode = 1
    fake_proc.communicate = AsyncMock(return_value=(b"", b"ERROR: Private video"))

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = fake_proc

        with pytest.raises(DownloaderError) as exc_info:
            await download_audio("https://www.youtube.com/watch?v=private", "mp3", "task-err")

        assert "ERROR: Private video" in str(exc_info.value)

def test_cleanup_task_files_non_existent():
    # Should not raise exception
    cleanup_task_files("/path/that/does/not/exist")

@pytest.mark.anyio
async def test_bot_check_error_includes_hint_when_cookies_have_no_login(tmp_path, monkeypatch):
    # Bot-check com cookies.txt sem sessão logada deve anexar a dica de reexport.
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tPREF\tx\n")
    monkeypatch.setattr("app.downloader.YTDLP_COOKIES_FILE", str(cookies))

    fake_proc = MagicMock()
    fake_proc.returncode = 1
    fake_proc.communicate = AsyncMock(return_value=(b"", b"ERROR: [youtube] abc: Sign in to confirm you're not a bot"))

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = fake_proc

        with pytest.raises(DownloaderError) as exc_info:
            await download_audio("https://www.youtube.com/watch?v=abc", "mp3", "task-hint")

        assert "Sign in to confirm" in str(exc_info.value)
        assert "NÃO contém sessão logada" in str(exc_info.value)
        assert "SID/LOGIN_INFO" in str(exc_info.value)

@pytest.mark.anyio
async def test_bot_check_error_without_cookies_file_includes_hint(monkeypatch):
    # Bot-check sem nenhum cookies.txt deve indicar como configurar.
    monkeypatch.setattr("app.downloader.YTDLP_COOKIES_FILE", "/caminho/que/nao/existe.txt")

    fake_proc = MagicMock()
    fake_proc.returncode = 1
    fake_proc.communicate = AsyncMock(return_value=(b"", b"ERROR: [youtube] abc: Sign in to confirm you're not a bot"))

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = fake_proc

        with pytest.raises(DownloaderError) as exc_info:
            await download_audio("https://www.youtube.com/watch?v=abc", "mp3", "task-hint2")

        assert "não há cookies.txt" in str(exc_info.value)

@pytest.mark.anyio
async def test_process_error_without_bot_check_has_no_hint(tmp_path, monkeypatch):
    # Erros comuns (privado, indisponível) não devem ganhar a dica de cookies.
    fake_proc = MagicMock()
    fake_proc.returncode = 1
    fake_proc.communicate = AsyncMock(return_value=(b"", b"ERROR: Private video"))

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = fake_proc

        with pytest.raises(DownloaderError) as exc_info:
            await download_audio("https://www.youtube.com/watch?v=priv", "mp3", "task-plain")

        assert "Aviso" not in str(exc_info.value)

@pytest.mark.anyio
async def test_download_audio_passes_cookies_and_js_runtime(tmp_path, monkeypatch):
    # O comando enviado ao yt-dlp deve carregar os cookies quando o arquivo
    # existe e habilitar um runtime JS para os desafios do YouTube.
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr("app.downloader.YTDLP_COOKIES_FILE", str(cookies))

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

        result = await download_audio("https://www.youtube.com/watch?v=123", "mp3", "task-ck")
        cmd = list(mock_exec.call_args[0])

        assert "--js-runtimes" in cmd
        assert cmd[cmd.index("--js-runtimes") + 1] == "node"
        assert "--cookies" in cmd
        assert cmd[cmd.index("--cookies") + 1] == str(cookies)
        cleanup_task_files(result.temp_dir)

@pytest.mark.anyio
async def test_download_audio_without_cookies_file(monkeypatch):
    # Sem arquivo de cookies a flag não deve ser passada ao yt-dlp.
    monkeypatch.setattr("app.downloader.YTDLP_COOKIES_FILE", "/caminho/que/nao/existe.txt")

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

        result = await download_audio("https://www.youtube.com/watch?v=123", "mp3", "task-no-ck")
        cmd = list(mock_exec.call_args[0])

        assert "--cookies" not in cmd
        cleanup_task_files(result.temp_dir)
