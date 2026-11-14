import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass

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
        "yt-dlp",
        "--no-playlist",
        "--extract-audio",
        "--audio-format", audio_format,
        "--audio-quality", "0",
        "--no-warnings",
        "-o", os.path.join(temp_dir, "%(title)s.%(ext)s"),
        str(url),
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode(errors="replace").strip() or "Erro desconhecido ao processar com yt-dlp."
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
