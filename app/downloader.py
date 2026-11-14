import asyncio
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass

# Caminho do arquivo de cookies (pode ser configurado via env YTDLP_COOKIES_FILE)
YTDLP_COOKIES_FILE = os.environ.get("YTDLP_COOKIES_FILE", "/opt/projects/baixa-music/cookies.txt")

# Cookies que só existem em sessão logada do YouTube
_LOGIN_COOKIES = ("SID", "LOGIN_INFO", "SAPISID")

def _cookies_tem_login(caminho: str) -> bool:
    """Confere se o arquivo de cookies contém cookies de sessão logada."""
    try:
        with open(caminho, "r", encoding="utf-8", errors="replace") as f:
            conteudo = f.read()
    except OSError:
        return False
    return any(f"\t{name}\t" in conteudo for name in _LOGIN_COOKIES)

@dataclass
class DownloadResult:
    task_id: str
    title: str
    file_path: str
    format: str
    temp_dir: str

class DownloaderError(Exception):
    """Exceção levantada quando ocorre erro durante a execução do yt-dlp."""
    pass

async def download_audio(url: str, audio_format: str, task_id: str) -> DownloadResult:
    """
    Executa o yt-dlp em um subprocesso seguro para extrair o áudio do vídeo na URL.
    """
    temp_dir = tempfile.mkdtemp(prefix=f"baixa_yt_{task_id}_")

    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--extract-audio",
        "--audio-format", audio_format,
        "--audio-quality", "0",
        # fetch_pot=always: sessão anônima também negocia PO token com o
        # provider bgutil (docker em 127.0.0.1:4416), contornando o bot-check
        # que o YouTube aplica a IPs de datacenter.
        "--extractor-args", "youtube:player_client=tv,android,web;fetch_pot=always",
        # O YouTube exige resolução de desafios JS (nsig/PO token); sem um
        # runtime JS a extração do cliente web falha ou perde formatos.
        "--js-runtimes", "node",
        "--retries", "3",
        "--fragment-retries", "3",
        "--no-warnings",
        "-o", os.path.join(temp_dir, "%(title)s.%(ext)s"),
    ]

    # Cookies de sessão autenticada contornam bloqueios de IP de datacenter
    # (bot-check/403); o arquivo é opcional e a flag só entra se existir.
    if os.path.isfile(YTDLP_COOKIES_FILE):
        cmd += ["--cookies", YTDLP_COOKIES_FILE]

    cmd.append(str(url))

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode(errors="replace").strip() or "Erro desconhecido ao processar com yt-dlp."
            if "Sign in to confirm" in error_msg:
                if not os.path.isfile(YTDLP_COOKIES_FILE):
                    error_msg += (
                        "\n\nAviso: este vídeo exige sessão logada e não há cookies.txt"
                        " no servidor. Exporte os cookies de um navegador logado no YouTube."
                    )
                elif not _cookies_tem_login(YTDLP_COOKIES_FILE):
                    error_msg += (
                        "\n\nAviso: o cookies.txt atual NÃO contém sessão logada"
                        " (faltam SID/LOGIN_INFO) — provavelmente foi exportado de um"
                        " navegador deslogado. Reexporte logado e substitua o arquivo."
                    )
            cleanup_task_files(temp_dir)
            raise DownloaderError(error_msg)

        # Procura o arquivo gerado com a extensão esperada
        target_files = [
            f for f in os.listdir(temp_dir)
            if f.lower().endswith(f".{audio_format.lower()}")
        ]

        if not target_files:
            # Caso o ffmpeg tenha mantido outra extensão ou nome
            all_files = os.listdir(temp_dir)
            if not all_files:
                cleanup_task_files(temp_dir)
                raise DownloaderError("Nenhum arquivo de áudio foi gerado pelo processo.")
            target_file_name = all_files[0]
        else:
            target_file_name = target_files[0]

        file_path = os.path.join(temp_dir, target_file_name)
        title = os.path.splitext(target_file_name)[0]

        return DownloadResult(
            task_id=task_id,
            title=title,
            file_path=file_path,
            format=audio_format,
            temp_dir=temp_dir
        )

    except Exception:
        cleanup_task_files(temp_dir)
        raise

def cleanup_task_files(temp_dir: str) -> None:
    """Remove o diretório temporário e quaisquer arquivos nele contidos."""
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
