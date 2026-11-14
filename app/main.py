import os
import uuid
from typing import Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.schemas import ConvertRequest, ConvertResponse, AudioFormat
from app.downloader import download_audio, cleanup_task_files, DownloaderError

app = FastAPI(title="Baixa YouTube", version="1.0.0")

# Armazenamento em memória de tarefas prontas para download
active_downloads: Dict[str, Dict[str, Any]] = {}

MEDIA_TYPES = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "wav": "audio/wav",
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def get_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_file):
        raise HTTPException(status_code=404, detail="Interface web não encontrada.")
    with open(index_file, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)

@app.post("/api/convert", response_model=ConvertResponse)
async def convert_video(payload: ConvertRequest):
    task_id = str(uuid.uuid4())
    format_str = payload.format.value

    try:
        result = await download_audio(
            url=str(payload.url),
            audio_format=format_str,
            task_id=task_id
        )
    except DownloaderError as e:
        raise HTTPException(status_code=422, detail=f"Erro ao processar áudio: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no servidor: {str(e)}")

    filename = os.path.basename(result.file_path)
    active_downloads[result.task_id] = {
        "file_path": result.file_path,
        "filename": filename,
        "format": format_str,
        "temp_dir": result.temp_dir,
    }

    return ConvertResponse(
        task_id=result.task_id,
        title=result.title,
        format=payload.format,
        download_url=f"/api/download/{result.task_id}"
    )

def _cleanup_task(task_id: str, temp_dir: str):
    """Executado em segundo plano após o streaming do arquivo."""
    active_downloads.pop(task_id, None)
    cleanup_task_files(temp_dir)

@app.get("/api/download/{task_id}")
async def download_file(task_id: str, background_tasks: BackgroundTasks):
    task_data = active_downloads.get(task_id)
    if not task_data:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado ou já expirado.")

    file_path = task_data["file_path"]
    if not os.path.exists(file_path):
        active_downloads.pop(task_id, None)
        raise HTTPException(status_code=404, detail="Arquivo físico não encontrado em disco.")

    media_type = MEDIA_TYPES.get(task_data["format"], "application/octet-stream")
    background_tasks.add_task(_cleanup_task, task_id, task_data["temp_dir"])

    return FileResponse(
        path=file_path,
        filename=task_data["filename"],
        media_type=media_type,
        content_disposition_type="attachment"
    )
