"""Application configuration loaded from environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration for the Insurance Claim Settlement Agent."""

    # ── Application ──
    app_name: str = "Insurance Claim Settlement Agent"
    app_env: str = "development"
    debug: bool = True

    # ── Server ──
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Paths ──
    data_dir: Path = Path("./data")
    storage_dir: Path = Path("./storage")
    reports_dir: Path = Path("./reports")

    # ── OCR ──
    tesseract_cmd: str = ""
    poppler_path: str = ""

    # ── Embedding Model ──
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── FAISS ──
    faiss_index_dir: Path = Path("./storage/faiss_indexes")
    similarity_threshold: float = 0.45
    faiss_similarity_threshold: float = 1.2
    top_k_results: int = 5

    # ── Decision Engine ──
    use_llm_summary: bool = False

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


# Singleton instance
settings = Settings()
