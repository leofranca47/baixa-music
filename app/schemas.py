from enum import Enum
from pydantic import BaseModel, HttpUrl, field_validator

class AudioFormat(str, Enum):
    mp3 = "mp3"
    m4a = "m4a"
    wav = "wav"

class ConvertRequest(BaseModel):
    url: HttpUrl
    format: AudioFormat = AudioFormat.mp3

    @field_validator("url", mode="before")
    @classmethod
    def validate_url_string(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("URL deve ser uma string.")
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("A URL deve iniciar com http:// ou https://")
        return v

class ConvertResponse(BaseModel):
    task_id: str
    title: str
    format: AudioFormat
    download_url: str
