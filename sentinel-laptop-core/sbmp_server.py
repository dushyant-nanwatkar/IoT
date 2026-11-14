"""
Sentinel Laptop Core - Custom SBMP (Sentinel Binary Multiplex Protocol) Server
Listens on TCP 0.0.0.0:9000 with hardware H.264 demuxing, PCM audio streaming,
intercepted notification dispatch, and persistent ADB tunnel healing.
"""

import sys
import os
import struct
import json
import time
import wave
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List, Set
import numpy as np
import cv2

from config import settings
from ring_buffer import frame_buffer
from database import log_security_event, save_voice_note, save_telemetry

logger = logging.getLogger("sentinel.sbmp")

# PyAV Codec import with graceful fallback
try:
    import av
    HAS_PYAV = True
except ImportError:
    HAS_PYAV = False
    logger.warning("PyAV ('av') is not installed. Falling back to OpenCV image/stream parser.")


class SBMPServer:
    """
    Host-side implementation of the Sentinel Binary Multiplex Protocol (SBMP).
    Handles binary multiplexing across 6 distinct channels over a single low-latency TCP socket.
    """

    # Protocol Channel Constants
    CH_VIDEO_H264 = 0x01       # Phone -> Host: Raw H.264 Annex-B NAL Units
    CH_MIC_AUDIO = 0x02        # Phone -> Host: Raw 16kHz 16-bit Mono PCM Mic Audio
    CH_PHONE_SCREEN = 0x03     # Phone -> Host: Kiosk Screen Mirror & Android Notifications
    CH_INTERCOM_AUDIO = 0x04   # Host -> Phone: Intercom & TTS Audio Stream
    CH_PHONE_UI_STATE = 0x05   # Host -> Phone: UI Greeting, Notice, Camera Switch, Siren
    CH_TELEMETRY_TRIGGERS = 0x06 # Phone -> Host: Doorbell Ring, Voice Note Start/Stop, Telemetry

    def __init__(self):
        self.server: Optional[asyncio.Server] = None
        self.active_writer: Optional[asyncio.StreamWriter] = None
        self.active_client_addr: Optional[str] = None
        self.writer_lock = asyncio.Lock()

        # Hardware H.264 PyAV Decoder Context
        self.codec_context = None
        self._init_pyav_decoder()

        # Channel 0x02: Voice Note Recording State
        self.is_recording_voice_note: bool = False
        self.voice_note_buffer: bytearray = bytearray()
        self.voice_note_start_time: float = 0.0

        # Callbacks for WebSocket broadcaster & AI pipeline
        self.audio_listeners: Set[Callable[[bytes], None]] = set()
        self.event_listeners: Set[Callable[[Dict[str, Any]], None]] = set()
        self.transcription_callback: Optional[Callable[[str, float], Any]] = None

        # Telemetry State
        self.phone_telemetry: Dict[str, Any] = {
            "connected": False,
            "battery_pct": 0,
            "is_charging": False,
            "temp_c": 0.0,
            "last_seen": 0.0,
            "adb_tunnel_ok": False,
        }

        # ADB Tunnel Task
        self.adb_task: Optional[asyncio.Task] = None
        self.is_running: bool = False

    def _init_pyav_decoder(self) -> None:
        """Initialize or reset the PyAV H.264 decoding context."""
        if HAS_PYAV:
            try:
                self.codec_context = av.CodecContext.create("h264", "r")
                logger.info("Hardware/C-level PyAV H.264 NAL decoder successfully initialized.")
            except Exception as e:
                logger.error(f"Failed to create PyAV CodecContext: {e}")
                self.codec_context = None

    def register_audio_listener(self, callback: Callable[[bytes], None]) -> None:
        """Register a callback for live doorway mic PCM audio chunks."""
        self.audio_listeners.add(callback)

    def unregister_audio_listener(self, callback: Callable[[bytes], None]) -> None:
        self.audio_listeners.discard(callback)

    def register_event_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for real-time events to push to WebSocket clients."""
        self.event_listeners.add(callback)

    def unregister_event_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self.event_listeners.discard(callback)

    def set_transcription_handler(self, callback: Callable[[str, float], Any]) -> None:
        """Set the GPU Whisper transcription handler."""
        self.transcription_callback = callback

    def _broadcast_event(self, event_data: Dict[str, Any]) -> None:
        """Forward an event to all registered listeners (e.g. WebSocket clients)."""
        for listener in list(self.event_listeners):
            try:
                listener(event_data)
            except Exception as e:
                logger.debug(f"Error in event listener: {e}")

    # ========================================================================
    # Downstream Helpers (Host -> Phone)
    # ========================================================================

    async def send_audio_to_phone(self, pcm_bytes: bytes) -> bool:
        """
        Stream raw 16kHz 16-bit Mono PCM audio to the phone speaker (Channel 0x04).
        Used for two-way intercom and synthesized edge-tts greetings.
        """
        if not self.active_writer:
            return False

        header = struct.pack(">BII", self.CH_INTERCOM_AUDIO, int(time.time() * 1000) & 0xFFFFFFFF, len(pcm_bytes))
        async with self.writer_lock:
            try:
                self.active_writer.write(header + pcm_bytes)
                await self.active_writer.drain()
                return True
            except Exception as e:
                logger.error(f"Failed to send audio to phone: {e}")
                return False

    async def send_ui_state_to_phone(self, json_dict: Dict[str, Any]) -> bool:
        """
        Send display commands & UI updates to the Doorbell Phone screen (Channel 0x05).
        Example payload: {"action": "DISPLAY_GREETING", "name": "Dushyant", "role": "Family"}
        """
        if not self.active_writer:
            logger.warning("No active phone connection to receive UI state.")
            return False

        try:
            payload = json.dumps(json_dict).encode("utf-8")
            header = struct.pack(">BII", self.CH_PHONE_UI_STATE, int(time.time() * 1000) & 0xFFFFFFFF, len(payload))
            async with self.writer_lock:
                self.active_writer.write(header + payload)
                await self.active_writer.drain()
            logger.info(f"Dispatched Channel 0x05 UI State to phone: {json_dict.get('action')}")
            return True
        except Exception as e:
            logger.error(f"Failed to send UI state to phone: {e}")
            return False

    # ========================================================================
    # Channel Demuxing & Protocol Handlers
    # ========================================================================

    async def _handle_video_h264(self, payload: bytes, timestamp_ms: int) -> None:
        """
        Channel 0x01: Decode Raw H.264 Annex-B NAL Units via PyAV and push into FrameRingBuffer.
        """
        frame_decoded = False

        if HAS_PYAV and self.codec_context:
            try:
                packets = self.codec_context.parse(payload)
                for packet in packets:
                    frames = self.codec_context.decode(packet)
                    for frame in frames:
                        bgr = frame.to_ndarray(format="bgr24")
                        frame_buffer.push_raw_frame(bgr, timestamp_ms)
                        frame_decoded = True
            except Exception as e:
                logger.debug(f"PyAV NAL parse/decode warning: {e}")

        # Robust Fallback: Check if payload is direct compressed image (JPEG/PNG)
        if not frame_decoded and len(payload) > 4:
            if payload[:2] == b"\xff\xd8" or payload[:4] == b"\x89PNG":
                try:
                    np_arr = np.frombuffer(payload, dtype=np.uint8)
                    bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    if bgr is not None:
                        frame_buffer.push_raw_frame(bgr, timestamp_ms)
                except Exception as e:
                    logger.debug(f"Direct image decode fallback error: {e}")

    async def _handle_mic_audio(self, payload: bytes, timestamp_ms: int) -> None:
        """
        Channel 0x02: Handle Raw 16kHz 16-bit Mono PCM Mic Audio.
        Broadcast to clients for intercom and buffer for Whisper if recording a voice note.
        """
        # 1. Forward live mic chunk to registered WebSocket audio listeners
        for listener in list(self.audio_listeners):
            try:
                listener(payload)
            except Exception as e:
                logger.debug(f"Audio listener dispatch error: {e}")

        # 2. Accumulate if voice note recording is active
        if self.is_recording_voice_note:
            self.voice_note_buffer.extend(payload)

    async def _handle_phone_screen_and_notifications(self, payload: bytes, timestamp_ms: int) -> None:
        """
        Channel 0x03: Handle Phone Screen Mirror & Intercepted Android OS Notifications.
        """
        # If payload starts with JSON '{', it is an intercepted Android OS notification
        if payload.startswith(b"{"):
            try:
                notif_data = json.loads(payload.decode("utf-8", errors="ignore"))
                pkg_name = notif_data.get("packageName", "unknown")
                title = notif_data.get("title", "Android Notification")
                text = notif_data.get("text", "")

                logger.info(f"Intercepted Android Notification from [{pkg_name}]: {title} - {text}")

                # Save to database
                await log_security_event(
                    event_type="NOTIFICATION_INTERCEPTED",
                    severity="INFO",
                    message=f"[{pkg_name}] {title}: {text}",
                    metadata={"notification": notif_data},
                )

                # Push real-time toast alert to Homeowner Client App
                toast_event = {
                    "type": "notification_toast",
                    "packageName": pkg_name,
                    "title": title,
                    "text": text,
                    "timestamp": timestamp_ms or int(time.time() * 1000),
                }
                self._broadcast_event(toast_event)
            except Exception as e:
                logger.error(f"Error parsing Channel 0x03 notification JSON: {e}")
        else:
            # Binary image bytes: Kiosk Screen Mirror snapshot
            try:
                frame_buffer.update_kiosk_screen(payload)
                # Persist latest screenshot
                preview_path = settings.DATA_DIR / "kiosk_screen_preview.jpg"
                with open(preview_path, "wb") as f:
                    f.write(payload)
            except Exception as e:
                logger.error(f"Error updating kiosk screen preview: {e}")

    async def _handle_telemetry_triggers(self, payload: bytes, timestamp_ms: int) -> None:
        """
        Channel 0x06: Doorbell Ring / Voice Note Start-Stop Triggers / Battery Telemetry.
        """
        try:
            data = json.loads(payload.decode("utf-8", errors="ignore"))
            event = data.get("event", "").upper()

            if event == "DOORBELL_RING":
                logger.warning(">>> DOORBELL RING TRIGGERED ON PHONE! <<<")
                # Save snapshot of visitor if available
                raw_frame, _ = frame_buffer.get_latest_raw_frame()
                snap_path = None
                if raw_frame is not None:
                    snap_filename = f"doorbell_{int(time.time())}.jpg"
                    snap_file = settings.SNAPSHOTS_DIR / snap_filename
                    cv2.imwrite(str(snap_file), raw_frame)
                    snap_path = f"/api/snapshots/{snap_filename}"

                # Log event in SQLite
                db_event = await log_security_event(
                    event_type="DOORBELL_RING",
                    severity="WARNING",
                    message="Doorbell chime was rung by a visitor at the doorway.",
                    snapshot_path=snap_path,
                    metadata={"source": "doorbell_button"},
                )

                # Broadcast to connected WebSocket clients
                self._broadcast_event({
                    "type": "doorbell_ring",
                    "id": db_event.id,
                    "message": "Doorbell chime rung!",
                    "snapshot_url": snap_path,
                    "timestamp": int(time.time() * 1000),
                })

            elif event == "VOICE_NOTE_START":
                logger.info("Voice note recording started from doorbell phone.")
                self.is_recording_voice_note = True
                self.voice_note_buffer.clear()
                self.voice_note_start_time = time.time()
                self._broadcast_event({
                    "type": "voice_note_state",
                    "state": "RECORDING",
                })

            elif event == "VOICE_NOTE_END":
                duration = time.time() - self.voice_note_start_time
                logger.info(f"Voice note recording ended. Duration: {duration:.2f}s, Bytes: {len(self.voice_note_buffer)}")
                self.is_recording_voice_note = False

                if len(self.voice_note_buffer) > 16000:  # At least 0.5 sec of audio
                    pcm_copy = bytes(self.voice_note_buffer)
                    self.voice_note_buffer.clear()
                    asyncio.create_task(self._process_and_transcribe_voice_note(pcm_copy, duration))
                else:
                    self.voice_note_buffer.clear()

            elif event == "TELEMETRY":
                bat = data.get("battery_pct", 0)
                charging = data.get("is_charging", False)
                temp = data.get("temp_c", 0.0)

                self.phone_telemetry.update({
                    "battery_pct": bat,
                    "is_charging": charging,
                    "temp_c": temp,
                    "last_seen": time.time(),
                })

                await save_telemetry(battery_pct=bat, is_charging=charging, temp_c=temp, adb_connected=True)

                self._broadcast_event({
                    "type": "telemetry_update",
                    "battery_pct": bat,
                    "is_charging": charging,
                    "temp_c": temp,
                })

        except Exception as e:
            logger.error(f"Error processing Channel 0x06 trigger payload: {e}")

    async def _process_and_transcribe_voice_note(self, pcm_bytes: bytes, duration: float) -> None:
        """
        Save PCM audio to .wav and invoke faster-whisper GPU transcription.
        """
        ts = int(time.time())
        wav_filename = f"voice_note_{ts}.wav"
        wav_path = settings.AUDIO_DIR / wav_filename

        try:
            # Write 16kHz, 16-bit Mono WAV
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(pcm_bytes)

            logger.info(f"Saved audio note to {wav_path}. Running Whisper transcription...")

            transcript_text = "Transcription in progress..."
            if self.transcription_callback:
                transcript_text = await self.transcription_callback(str(wav_path), duration)

            # Save in database
            note = await save_voice_note(
                audio_path=f"/api/voice-notes/{wav_filename}",
                transcript=transcript_text,
                duration_sec=duration,
            )

            # Also log as security event
            await log_security_event(
                event_type="VOICE_NOTE",
                severity="INFO",
                message=f"Voice Note received ({duration:.1f}s): {transcript_text}",
                metadata={"audio_url": f"/api/voice-notes/{wav_filename}", "transcript": transcript_text},
            )

            # Broadcast to Homeowner Client App
            self._broadcast_event({
                "type": "voice_note_transcribed",
                "id": note.id,
                "audio_url": f"/api/voice-notes/{wav_filename}",
                "transcript": transcript_text,
                "duration_sec": round(duration, 1),
                "timestamp": ts * 1000,
            })
        except Exception as e:
            logger.error(f"Failed to process and transcribe voice note: {e}")

    # ========================================================================
    # TCP Connection Handler
    # ========================================================================

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """
        Manage single or active phone TCP session over port 9000.
        Demultiplexes SBMP 9-byte binary header followed by payload.
        """
        peer = writer.get_extra_info("peername")
        logger.info(f"Android Doorbell Phone connected from {peer} via SBMP.")

        async with self.writer_lock:
            self.active_writer = writer
            self.active_client_addr = str(peer)
            self.phone_telemetry["connected"] = True
            self.phone_telemetry["last_seen"] = time.time()

        self._broadcast_event({
            "type": "phone_status",
            "connected": True,
            "peer": str(peer),
        })

        try:
            while self.is_running:
                # Read 9-byte SBMP header
                header_bytes = await reader.readexactly(settings.SBMP_HEADER_SIZE)
                channel_id, timestamp_ms, payload_len = struct.unpack(">BII", header_bytes)

                # Read exact payload
                payload = await reader.readexactly(payload_len)
                self.phone_telemetry["last_seen"] = time.time()

                # Dispatch according to channel
                if channel_id == self.CH_VIDEO_H264:
                    await self._handle_video_h264(payload, timestamp_ms)
                elif channel_id == self.CH_MIC_AUDIO:
                    await self._handle_mic_audio(payload, timestamp_ms)
                elif channel_id == self.CH_PHONE_SCREEN:
                    await self._handle_phone_screen_and_notifications(payload, timestamp_ms)
                elif channel_id == self.CH_TELEMETRY_TRIGGERS:
                    await self._handle_telemetry_triggers(payload, timestamp_ms)
                else:
                    logger.debug(f"Unhandled SBMP channel 0x{channel_id:02X} (len: {payload_len})")

        except asyncio.IncompleteReadError:
            logger.warning(f"Phone connection closed (IncompleteReadError from {peer}).")
        except ConnectionResetError:
            logger.warning(f"Phone connection reset by peer {peer}.")
        except Exception as e:
            logger.error(f"SBMP socket error with {peer}: {e}")
        finally:
            async with self.writer_lock:
                if self.active_writer == writer:
                    self.active_writer = None
                    self.active_client_addr = None
                    self.phone_telemetry["connected"] = False

            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

            logger.info(f"Phone session from {peer} terminated.")
            self._broadcast_event({
                "type": "phone_status",
                "connected": False,
            })

    # ========================================================================
    # ADB Tunnel Manager (Auto-Healing)
    # ========================================================================

    async def adb_tunnel_manager(self) -> None:
        """
        Background task that executes `adb reverse tcp:9000 tcp:9000` every 5 seconds.
        Ensures that whenever the Android phone is connected or re-plugged, the tunnel auto-heals.
        """
        adb_cmd = settings.ADB_PATH
        logger.info(f"Starting persistent ADB tunnel manager using '{adb_cmd}'...")

        while self.is_running:
            try:
                # Run `adb reverse tcp:9000 tcp:9000` asynchronously
                proc = await asyncio.create_subprocess_exec(
                    adb_cmd,
                    "reverse",
                    f"tcp:{settings.ADB_REVERSE_REMOTE}",
                    f"tcp:{settings.ADB_REVERSE_LOCAL}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode == 0:
                    if not self.phone_telemetry.get("adb_tunnel_ok"):
                        logger.info(f"ADB Tunnel healed: reverse tcp:{settings.ADB_REVERSE_REMOTE} -> tcp:{settings.ADB_REVERSE_LOCAL}")
                    self.phone_telemetry["adb_tunnel_ok"] = True
                else:
                    err_msg = stderr.decode().strip()
                    self.phone_telemetry["adb_tunnel_ok"] = False
                    logger.debug(f"ADB reverse check: {err_msg}")
            except FileNotFoundError:
                self.phone_telemetry["adb_tunnel_ok"] = False
                logger.debug(f"ADB executable not found at '{adb_cmd}'. Waiting for device or manual path.")
            except Exception as e:
                self.phone_telemetry["adb_tunnel_ok"] = False
                logger.debug(f"ADB tunnel error: {e}")

            await asyncio.sleep(settings.ADB_TUNNEL_INTERVAL_SEC)

    # ========================================================================
    # Server Lifecycle
    # ========================================================================

    async def start(self) -> None:
        """Start the SBMP TCP Server on 0.0.0.0:9000 and spawn ADB tunnel loop."""
        self.is_running = True
        self.server = await asyncio.start_server(
            self.handle_client,
            settings.SBMP_HOST,
            settings.SBMP_PORT,
        )
        addrs = ", ".join(str(sock.getsockname()) for sock in self.server.sockets)
        logger.info(f"SBMP TCP Server actively listening on {addrs}")

        # Spawn ADB tunnel manager background task
        self.adb_task = asyncio.create_task(self.adb_tunnel_manager())

    async def stop(self) -> None:
        """Gracefully terminate SBMP server and background tasks."""
        self.is_running = False
        if self.adb_task:
            self.adb_task.cancel()

        if self.active_writer:
            try:
                self.active_writer.close()
                await self.active_writer.wait_closed()
            except Exception:
                pass

        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("SBMP Server closed.")


# Global singleton SBMP Server instance
sbmp_server = SBMPServer()
