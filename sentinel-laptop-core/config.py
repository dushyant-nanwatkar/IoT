"""
Sentinel Laptop Core - Configuration Settings
Target Architecture: AMD Ryzen 7 250, 32GB DDR5, NVIDIA GeForce RTX 5060 (8GB VRAM)
"""

import os
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field


def find_default_adb_path() -> str:
    """Auto-detect ADB binary from PATH or standard Android SDK directories."""
    # 1. Environment variable override
    env_adb = os.environ.get("ADB_PATH")
    if env_adb and Path(env_adb).exists():
        return env_adb

    # 2. Check PATH
    import shutil
    path_adb = shutil.which("adb")
    if path_adb:
        return path_adb

    # 3. Common Windows paths
    user_home = Path.home()
    common_candidates = [
        user_home / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        Path("C:/Android/platform-tools/adb.exe"),
        Path("C:/Program Files/Android/platform-tools/adb.exe"),
    ]
    for candidate in common_candidates:
        if candidate.exists():
            return str(candidate)

    return "adb"  # Default fallback


class Settings(BaseSettings):
    # Base Directories
    BASE_DIR: Path = Path(__file__).resolve().parent
    DATA_DIR: Path = BASE_DIR / "data"
    SNAPSHOTS_DIR: Path = BASE_DIR / "data" / "snapshots"
    AUDIO_DIR: Path = BASE_DIR / "data" / "audio"
    FACES_DIR: Path = BASE_DIR / "data" / "faces"
    STATIC_DIR: Path = BASE_DIR / "static"

    # Database
    DATABASE_URL: str = Field(
        default=f"sqlite+aiosqlite:///{BASE_DIR / 'sentinel.db'}",
        description="Async SQLite database connection string",
    )

    # SBMP Protocol & TCP Server
    SBMP_HOST: str = "0.0.0.0"
    SBMP_PORT: int = 9000
    SBMP_HEADER_SIZE: int = 9  # struct.unpack(">BII", header_bytes)
    ADB_PATH: str = Field(default_factory=find_default_adb_path)
    ADB_TUNNEL_INTERVAL_SEC: float = 5.0
    ADB_REVERSE_LOCAL: int = 9000
    ADB_REVERSE_REMOTE: int = 9000

    # FastAPI & WebSockets
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: List[str] = ["*"]
    TARGET_STREAM_FPS: int = 30

    # Hardware & RTX 5060 Optimization
    DEVICE: str = "cuda:0"
    GPU_NAME: str = "NVIDIA GeForce RTX 5060 (8GB VRAM)"
    INFERENCE_FPS: float = 12.0  # Decoupled AI inference 10-15 Hz

    # Stage 1: Person & Loitering Detection
    YOLO_MODEL_NAME: str = "yolo11n.pt"
    YOLO_CONF_THRESHOLD: float = 0.45
    LOITERING_ALERT_THRESHOLD_SEC: float = 3.0
    INTRUDER_ALERT_COOLDOWN_SEC: float = 15.0

    # Stage 2: Face ID & InsightFace
    INSIGHTFACE_MODEL: str = "buffalo_l"
    FACE_MATCH_THRESHOLD: float = 0.48  # Cosine similarity threshold
    GREETING_COOLDOWN_SEC: float = 45.0
    TTS_VOICE: str = "en-US-ChristopherNeural"  # Natural crisp neural voice

    # Stage 3: Faster-Whisper
    WHISPER_MODEL: str = "small"
    WHISPER_DEVICE: str = "cuda"
    WHISPER_COMPUTE_TYPE: str = "float16"

    # Cloud Sync (Supabase)
    SUPABASE_URL: Optional[str] = os.environ.get("SUPABASE_URL", "")
    SUPABASE_KEY: Optional[str] = os.environ.get("SUPABASE_KEY", "")
    SUPABASE_BUCKET: str = "sentinel-snapshots"
    ENABLE_CLOUD_SYNC: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Global settings singleton
settings = Settings()

# Ensure directories exist
for path in [settings.DATA_DIR, settings.SNAPSHOTS_DIR, settings.AUDIO_DIR, settings.FACES_DIR, settings.STATIC_DIR]:
    path.mkdir(parents=True, exist_ok=True)
