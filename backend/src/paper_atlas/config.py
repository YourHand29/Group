from functools import lru_cache
import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    model_mode: str = Field(default="demo", pattern="^(demo)$")
    max_retries: int = Field(default=1, ge=0, le=3)
    max_document_chars: int = Field(default=120_000, ge=1_000, le=2_000_000)
    max_chunk_chars: int = Field(default=4_000, ge=500, le=20_000)
    frontend_origin: str = "http://localhost:3000"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        model_mode=os.getenv("PAPER_ATLAS_MODEL_MODE", "demo"),
        max_retries=int(os.getenv("PAPER_ATLAS_MAX_RETRIES", "1")),
        max_document_chars=int(os.getenv("PAPER_ATLAS_MAX_DOCUMENT_CHARS", "120000")),
        max_chunk_chars=int(os.getenv("PAPER_ATLAS_MAX_CHUNK_CHARS", "4000")),
        frontend_origin=os.getenv("PAPER_ATLAS_FRONTEND_ORIGIN", "http://localhost:3000"),
    )
