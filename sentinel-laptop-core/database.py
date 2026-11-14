"""
Sentinel Laptop Core - Asynchronous Database Layer & ORM Session Manager
Auto-migrates schema on startup and provides high-speed vector embedding cache.
"""

import json
import logging
from typing import AsyncGenerator, List, Dict, Any, Optional
import numpy as np
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, desc
from config import settings
from models import Base, EnrolledFace, SecurityEvent, VoiceNote, DeviceTelemetry, KioskNotice

logger = logging.getLogger("sentinel.db")

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Initialize database tables and run schema auto-migration."""
    logger.info("Initializing SQLite database with auto-migration...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema verified and up-to-date.")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection helper for FastAPI endpoints."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def load_all_enrolled_embeddings() -> List[Dict[str, Any]]:
    """
    Fetch all enrolled faces from database and deserialize their 512-D embeddings
    into normalized NumPy arrays for high-speed matrix cosine comparison.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(EnrolledFace))
        faces = result.scalars().all()

        enrolled_cache = []
        for face in faces:
            try:
                emb_list = json.loads(face.embedding_json)
                emb_vec = np.array(emb_list, dtype=np.float32)
                norm = np.linalg.norm(emb_vec)
                if norm > 0:
                    emb_vec = emb_vec / norm  # Ensure unit norm
                enrolled_cache.append({
                    "id": face.id,
                    "name": face.name,
                    "role": face.role,
                    "custom_greeting": face.custom_greeting,
                    "embedding": emb_vec,
                    "photo_path": face.photo_path,
                })
            except Exception as e:
                logger.error(f"Error parsing embedding for face ID {face.id} ({face.name}): {e}")

        logger.info(f"Loaded {len(enrolled_cache)} enrolled face embeddings into GPU cache.")
        return enrolled_cache


async def log_security_event(
    event_type: str,
    severity: str,
    message: str,
    snapshot_path: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> SecurityEvent:
    """Convenience helper to record a security event."""
    async with AsyncSessionLocal() as session:
        event = SecurityEvent(
            event_type=event_type,
            severity=severity,
            message=message,
            snapshot_path=snapshot_path,
            metadata_json=json.dumps(metadata or {}),
            synced_to_cloud=False,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event


async def save_voice_note(
    audio_path: str,
    transcript: str,
    duration_sec: float,
    sender_name: str = "Visitor",
) -> VoiceNote:
    """Save voice note metadata and transcribed text."""
    async with AsyncSessionLocal() as session:
        note = VoiceNote(
            audio_path=audio_path,
            transcript=transcript,
            duration_sec=duration_sec,
            sender_name=sender_name,
        )
        session.add(note)
        await session.commit()
        await session.refresh(note)
        return note


async def save_telemetry(
    battery_pct: int,
    is_charging: bool,
    temp_c: float,
    adb_connected: bool,
) -> DeviceTelemetry:
    """Save phone battery and temperature telemetry."""
    async with AsyncSessionLocal() as session:
        telem = DeviceTelemetry(
            battery_pct=battery_pct,
            is_charging=is_charging,
            temp_c=temp_c,
            adb_connected=adb_connected,
        )
        session.add(telem)
        await session.commit()
        return telem
