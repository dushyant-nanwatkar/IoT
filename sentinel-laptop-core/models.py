"""
Sentinel Laptop Core - Data Models (SQLAlchemy ORM & Pydantic Schemas)
"""

from datetime import datetime
from typing import List, Optional, Any, Dict
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base
from pydantic import BaseModel, Field

Base = declarative_base()


# ============================================================================
# SQLAlchemy ORM Models
# ============================================================================

class EnrolledFace(Base):
    __tablename__ = "enrolled_faces"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False, index=True)
    role = Column(String(64), default="Resident", nullable=False)
    custom_greeting = Column(String(256), nullable=True)
    embedding_json = Column(Text, nullable=False)  # JSON-encoded 512-D float list
    photo_path = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    # Types: INTRUDER_ALERT, FACE_RECOGNIZED, DOORBELL_RING, VOICE_NOTE, NOTIFICATION_INTERCEPTED, SYSTEM_ALERT
    severity = Column(String(32), default="INFO", nullable=False)  # CRITICAL, WARNING, INFO
    message = Column(Text, nullable=False)
    snapshot_path = Column(String(512), nullable=True)
    metadata_json = Column(Text, nullable=True)  # Detailed context (face name, package, battery, etc.)
    synced_to_cloud = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class VoiceNote(Base):
    __tablename__ = "voice_notes"

    id = Column(Integer, primary_key=True, index=True)
    audio_path = Column(String(512), nullable=False)
    transcript = Column(Text, nullable=True)
    duration_sec = Column(Float, default=0.0, nullable=False)
    sender_name = Column(String(128), default="Visitor", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class DeviceTelemetry(Base):
    __tablename__ = "device_telemetry"

    id = Column(Integer, primary_key=True, index=True)
    battery_pct = Column(Integer, nullable=False)
    is_charging = Column(Boolean, default=False, nullable=False)
    temp_c = Column(Float, default=0.0, nullable=False)
    adb_connected = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class KioskNotice(Base):
    __tablename__ = "kiosk_notices"

    id = Column(Integer, primary_key=True, index=True)
    text = Column(Text, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ============================================================================
# Pydantic Request / Response Schemas
# ============================================================================

class FaceEnrollRequest(BaseModel):
    name: str = Field(..., description="Full Name of the resident or frequent visitor")
    role: str = Field(default="Family", description="Role: Family, Resident, VIP, Delivery, Guest")
    custom_greeting: Optional[str] = Field(None, description="Spoken greeting, e.g. 'Welcome home, John'")


class FaceResponse(BaseModel):
    id: int
    name: str
    role: str
    custom_greeting: Optional[str] = None
    photo_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SecurityEventResponse(BaseModel):
    id: int
    event_type: str
    severity: str
    message: str
    snapshot_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    synced_to_cloud: bool
    created_at: datetime

    class Config:
        from_attributes = True


class VoiceNoteResponse(BaseModel):
    id: int
    audio_url: str
    transcript: Optional[str]
    duration_sec: float
    created_at: datetime

    class Config:
        from_attributes = True


class KioskNoticeRequest(BaseModel):
    text: str = Field(..., description="Notice message displayed on the Doorbell Phone")
    speak_tts: bool = Field(default=False, description="Whether to also speak this notice via TTS on phone speaker")


class CameraControlRequest(BaseModel):
    action: str = Field(..., description="Action: toggle_camera, siren_on, siren_off, snapshot")
    lens: Optional[str] = Field("front", description="Lens: front or back")


class SystemStatusResponse(BaseModel):
    gpu_name: str
    gpu_vram_used_mb: float
    gpu_vram_total_mb: float
    gpu_utilization_pct: float
    ram_usage_gb: float
    ram_total_gb: float
    stream_fps: float
    inference_fps: float
    adb_tunnel_ok: bool
    phone_connected: bool
    phone_battery_pct: Optional[int]
    phone_charging: Optional[bool]
    phone_temp_c: Optional[float]
    enrolled_faces_count: int
    active_ws_clients: int
    lan_ip: Optional[str] = None


class FaceEnrollCameraRequest(BaseModel):
    name: str = Field(..., description="Full Name of the resident or frequent visitor")
    role: str = Field(default="Family", description="Role: Family, Resident, VIP, Delivery, Guest")
    custom_greeting: Optional[str] = Field(None, description="Spoken greeting, e.g. 'Welcome home, John'")
    photo_base64: Optional[str] = Field(None, description="Base64 encoded JPEG/PNG frame from webcam or camera")
    use_doorbell_stream: bool = Field(default=False, description="Whether to capture live frame from doorway camera")


class KioskRingRequest(BaseModel):
    message: Optional[str] = Field("Visitor rang the doorbell", description="Optional message or reason")
    visitor_photo_base64: Optional[str] = Field(None, description="Optional snapshot from kiosk camera")


class KioskTelemetryRequest(BaseModel):
    battery_pct: int = Field(..., ge=0, le=100)
    is_charging: bool = Field(default=False)
    temp_c: float = Field(default=30.0)
    wifi_rssi: Optional[int] = Field(None, description="Wi-Fi signal strength in dBm")


class KioskStateResponse(BaseModel):
    notice_text: Optional[str] = None
    siren_active: bool = False
    camera_lens: str = "back"
    active_greeting: Optional[Dict[str, Any]] = None


class KioskDiscoveryResponse(BaseModel):
    server_name: str
    lan_ip: str
    http_port: int
    sbmp_port: int
    ws_client_url: str
    ws_kiosk_url: str
    endpoints: Dict[str, str]

