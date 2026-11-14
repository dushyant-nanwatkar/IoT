"""
Sentinel Laptop Core - RTX 5060 Hardware AI Pipeline (Decoupled Worker)
Executes YOLOv11 person tracking, InsightFace Buffalo_L 512-D cosine matching,
Loitering detection, Edge-TTS audio greeting synthesis, and Whisper transcription.
"""

import os
import sys
import time
import math
import asyncio
import logging
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
import cv2

from config import settings
from ring_buffer import frame_buffer
from database import load_all_enrolled_embeddings, log_security_event
from sbmp_server import sbmp_server
from cloud_sync import cloud_sync_queue

logger = logging.getLogger("sentinel.gpu")

# Optional PyAV import for audio conversion
try:
    import av
    HAS_PYAV = True
except ImportError:
    HAS_PYAV = False

# Optional Edge-TTS
try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

# Optional Ultralytics YOLO
try:
    from ultralytics import YOLO
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False

# Optional InsightFace
try:
    import insightface
    from insightface.app import FaceAnalysis
    HAS_INSIGHTFACE = True
except ImportError:
    HAS_INSIGHTFACE = False

# Optional Faster-Whisper
try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False


class GPUPipeline:
    """
    Dedicated worker running on NVIDIA RTX 5060 (8GB VRAM).
    Decoupled from 30 FPS video ingest loop, polling frames at 10-15 Hz.
    """

    def __init__(self):
        self.device = settings.DEVICE
        self.is_running = False
        self.worker_thread: Optional[threading.Thread] = None

        # Models
        self.yolo_model = None
        self.face_app = None
        self.whisper_model = None

        # Enrolled Face Embedding Cache: list of dicts with 512-D float32 numpy arrays
        self.enrolled_faces: List[Dict[str, Any]] = []
        self.enrolled_matrix: Optional[np.ndarray] = None  # (N, 512) matrix
        self.enrolled_lock = threading.Lock()

        # Loitering & Tracking State: {track_id: {first_seen, last_seen, bbox, name, role, alerted}}
        self.tracked_persons: Dict[int, Dict[str, Any]] = {}
        self.next_track_id: int = 1
        self.loitering_threshold = settings.LOITERING_ALERT_THRESHOLD_SEC

        # Cooldown management for greetings and alerts
        self.greeting_history: Dict[str, float] = {}  # name -> last_greeting_timestamp
        self.last_intruder_alert_time: float = 0.0

        # Performance metrics
        self.inference_fps = 0.0
        self.inference_times: List[float] = []

        # Event loop reference for async dispatch
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def initialize_models(self) -> None:
        """
        Load neural networks onto NVIDIA RTX 5060 with CUDA acceleration.
        """
        logger.info(f"Initializing AI Pipeline on {settings.GPU_NAME} ({self.device})...")

        # 1. Initialize YOLOv11
        if HAS_YOLO:
            try:
                self.yolo_model = YOLO(settings.YOLO_MODEL_NAME)
                # Test forward pass on GPU
                logger.info("YOLOv11 model loaded successfully.")
            except Exception as e:
                logger.error(f"YOLOv11 GPU load error: {e}. Falling back to default CPU/heuristic.")
                self.yolo_model = None
        else:
            logger.warning("ultralytics not installed. Running in heuristic/mock CV mode.")

        # 2. Initialize InsightFace Buffalo_L
        if HAS_INSIGHTFACE:
            try:
                # Prioritize CUDAExecutionProvider
                providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
                self.face_app = FaceAnalysis(name=settings.INSIGHTFACE_MODEL, providers=providers)
                self.face_app.prepare(ctx_id=0, det_size=(640, 640))
                logger.info("InsightFace Buffalo_L (512-D) successfully initialized with CUDA.")
            except Exception as e:
                logger.error(f"InsightFace CUDA initialization warning: {e}. Falling back to CPU.")
                try:
                    self.face_app = FaceAnalysis(name=settings.INSIGHTFACE_MODEL, providers=["CPUExecutionProvider"])
                    self.face_app.prepare(ctx_id=-1, det_size=(640, 640))
                except Exception as inner_e:
                    logger.error(f"InsightFace CPU fallback failed: {inner_e}")
                    self.face_app = None
        else:
            logger.warning("insightface not installed. Running in mock Face ID mode.")

        # 3. Initialize Faster-Whisper
        if HAS_WHISPER:
            try:
                self.whisper_model = WhisperModel(
                    settings.WHISPER_MODEL,
                    device=settings.WHISPER_DEVICE,
                    compute_type=settings.WHISPER_COMPUTE_TYPE,
                )
                logger.info(f"Faster-Whisper '{settings.WHISPER_MODEL}' initialized on {settings.WHISPER_DEVICE} ({settings.WHISPER_COMPUTE_TYPE}).")
            except Exception as e:
                logger.warning(f"Faster-Whisper GPU init failed ({e}). Falling back to CPU int8.")
                try:
                    self.whisper_model = WhisperModel(settings.WHISPER_MODEL, device="cpu", compute_type="int8")
                except Exception as inner_e:
                    logger.error(f"Faster-Whisper CPU init failed: {inner_e}")
                    self.whisper_model = None

    def refresh_enrolled_faces(self, faces: List[Dict[str, Any]]) -> None:
        """
        Update the in-memory enrolled faces cache from SQLite database.
        Precomputes the (N, 512) normalized matrix for instant dot-product cosine matching.
        """
        with self.enrolled_lock:
            self.enrolled_faces = faces
            if faces:
                embeddings = [f["embedding"] for f in faces]
                self.enrolled_matrix = np.vstack(embeddings).astype(np.float32)
                logger.info(f"Loaded {len(faces)} faces into GPU cosine comparison matrix.")
            else:
                self.enrolled_matrix = None
                logger.info("Enrolled faces database is currently empty.")

    # ========================================================================
    # Audio Synthesis & Intercom Bridge
    # ========================================================================

    async def speak_greeting_on_phone(self, text: str) -> None:
        """
        Synthesize neural speech via Edge-TTS, convert to 16kHz 16-bit Mono PCM,
        and stream over Channel 0x04 to the Doorbell Phone speaker.
        """
        logger.info(f"Synthesizing Doorbell TTS: '{text}'")
        try:
            if not HAS_EDGE_TTS:
                logger.warning("edge-tts not installed; generating fallback chime audio.")
                pcm = self._generate_synthetic_chime(frequency=880, duration=0.8)
                await sbmp_server.send_audio_to_phone(pcm)
                return

            temp_mp3 = settings.AUDIO_DIR / f"tts_{int(time.time() * 1000)}.mp3"
            communicate = edge_tts.Communicate(text, settings.TTS_VOICE)
            await communicate.save(str(temp_mp3))

            # Convert MP3 to 16kHz Mono PCM
            pcm_data = self._convert_audio_file_to_pcm16(temp_mp3)

            # Cleanup temp file
            if temp_mp3.exists():
                try:
                    temp_mp3.unlink()
                except Exception:
                    pass

            if pcm_data:
                await sbmp_server.send_audio_to_phone(pcm_data)
                logger.info(f"Streamed {len(pcm_data)} bytes of TTS PCM to phone speaker.")

        except Exception as e:
            logger.error(f"Error synthesizing and streaming TTS greeting: {e}")

    def _convert_audio_file_to_pcm16(self, audio_file: Path) -> bytes:
        """Convert an audio file (MP3/WAV/AAC) to 16kHz 16-bit Mono PCM."""
        if HAS_PYAV:
            try:
                container = av.open(str(audio_file))
                resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
                chunks = []
                for frame in container.decode(audio=0):
                    for resampled in resampler.resample(frame):
                        chunks.append(resampled.to_ndarray().tobytes())
                return b"".join(chunks)
            except Exception as e:
                logger.warning(f"PyAV audio transcode failed: {e}. Using fallback chime.")

        return self._generate_synthetic_chime(frequency=520, duration=1.0)

    def _generate_synthetic_chime(self, frequency: float = 659.25, duration: float = 0.5) -> bytes:
        """Generate a gentle synthetic sine wave chime in 16kHz 16-bit Mono PCM."""
        sample_rate = 16000
        n_samples = int(sample_rate * duration)
        t = np.linspace(0, duration, n_samples, endpoint=False)
        envelope = np.exp(-3.5 * t)  # Exponential decay
        sine_wave = (np.sin(2 * np.pi * frequency * t) * envelope * 24000).astype(np.int16)
        return sine_wave.tobytes()

    # ========================================================================
    # Voice Note Transcription
    # ========================================================================

    async def transcribe_audio_file(self, wav_path: str, duration: float) -> str:
        """
        Transcribe an audio file using Faster-Whisper on RTX 5060 (float16).
        """
        if not self.whisper_model:
            return "Transcription unavailable (Whisper model not initialized)."

        def _run_whisper():
            try:
                segments, info = self.whisper_model.transcribe(
                    wav_path,
                    beam_size=5,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500),
                )
                text_parts = [segment.text.strip() for segment in segments]
                full_text = " ".join(text_parts).strip()
                return full_text or "(Silent audio or no clear speech detected)"
            except Exception as e:
                logger.error(f"Whisper transcription failed: {e}")
                return f"(Transcription error: {str(e)})"

        loop = self.loop or asyncio.get_event_loop()
        return await loop.run_in_executor(None, _run_whisper)

    # ========================================================================
    # Cosine Matching & Face Recognition
    # ========================================================================

    def match_face(self, face_embedding: np.ndarray) -> Tuple[Optional[str], Optional[str], float]:
        """
        Compute cosine similarity between a detected face embedding and the enrolled face database.
        Returns: (name, role, confidence) or (None, None, 0.0)
        """
        with self.enrolled_lock:
            if self.enrolled_matrix is None or len(self.enrolled_faces) == 0:
                return None, None, 0.0

            # Normalize query vector
            norm = np.linalg.norm(face_embedding)
            if norm == 0:
                return None, None, 0.0
            query = (face_embedding / norm).astype(np.float32)

            # Cosine similarity matrix multiplication: (N, 512) x (512,) -> (N,)
            similarities = np.dot(self.enrolled_matrix, query)
            best_idx = int(np.argmax(similarities))
            best_score = float(similarities[best_idx])

            if best_score >= settings.FACE_MATCH_THRESHOLD:
                matched = self.enrolled_faces[best_idx]
                return matched["name"], matched["role"], best_score

            return None, None, best_score

    # ========================================================================
    # Intruder Alert & Threat Detection
    # ========================================================================

    def trigger_intruder_alert(self, frame: np.ndarray, duration_sec: float, track_id: int) -> None:
        """
        Handle loitering detection: save snapshot, trigger phone warning,
        dispatch toast to homeowner client app, and queue Supabase cloud upload.
        """
        now = time.time()
        if now - self.last_intruder_alert_time < settings.INTRUDER_ALERT_COOLDOWN_SEC:
            return  # Debounce spamming alerts

        self.last_intruder_alert_time = now
        logger.warning(f"!!! INTRUDER ALERT TRIGGERED: Person loitering for {duration_sec:.1f}s (Track #{track_id}) !!!")

        # 1. Save High-Resolution Snapshot
        snap_filename = f"intruder_{int(now)}_{track_id}.jpg"
        snap_path = settings.SNAPSHOTS_DIR / snap_filename
        cv2.imwrite(str(snap_path), frame)
        snapshot_url = f"/api/snapshots/{snap_filename}"

        # 2. Dispatch async database & network tasks
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._dispatch_intruder_alert_async(snap_path, snapshot_url, duration_sec, track_id),
                self.loop,
            )

    async def _dispatch_intruder_alert_async(
        self,
        snap_path: Path,
        snapshot_url: str,
        duration_sec: float,
        track_id: int,
    ) -> None:
        # A. Send UI Warning to Doorbell Phone screen (0x05)
        await sbmp_server.send_ui_state_to_phone({
            "action": "DISPLAY_WARNING",
            "title": "SECURITY ALERT",
            "message": "Recording in Progress. Property Security Active.",
            "duration_sec": 8,
        })

        # B. Audible Voice Warning to Phone Speaker (0x04)
        warning_msg = "Security alert. You are being recorded on camera. The homeowner has been notified."
        await self.speak_greeting_on_phone(warning_msg)

        # C. Log to SQLite
        event = await log_security_event(
            event_type="INTRUDER_ALERT",
            severity="CRITICAL",
            message=f"Unrecognized person loitering at doorway for {duration_sec:.1f} seconds.",
            snapshot_path=snapshot_url,
            metadata={"loiter_seconds": round(duration_sec, 1), "track_id": track_id},
        )

        # D. Broadcast instant toast / event to Homeowner Client App
        sbmp_server._broadcast_event({
            "type": "intruder_alert",
            "id": event.id,
            "message": f"Intruder detected loitering ({duration_sec:.1f}s)",
            "snapshot_url": snapshot_url,
            "severity": "CRITICAL",
            "timestamp": int(time.time() * 1000),
        })

        # E. Queue async cloud sync to Supabase
        await cloud_sync_queue.enqueue(
            event_id=event.id,
            event_type="INTRUDER_ALERT",
            severity="CRITICAL",
            message=event.message,
            snapshot_file_path=str(snap_path),
            metadata={"loiter_seconds": duration_sec, "track_id": track_id},
        )

    # ========================================================================
    # HUD Drawing & Visual Overlay
    # ========================================================================

    def draw_hud(
        self,
        frame: np.ndarray,
        detections: List[Dict[str, Any]],
        fps: float,
    ) -> np.ndarray:
        """
        Draw sleek, cyberpunk/tactical HUD bounding boxes and metrics onto frame.
        """
        annotated = frame.copy()
        h, w, _ = annotated.shape

        # Draw Top Status Bar
        cv2.rectangle(annotated, (0, 0), (w, 36), (18, 22, 28), -1)
        cv2.putText(
            annotated,
            f"SENTINEL AI | RTX 5060 | AI: {fps:.1f} FPS",
            (14, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 220, 180),
            1,
            cv2.LINE_AA,
        )

        ts_str = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(
            annotated,
            ts_str,
            (w - 200, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (180, 190, 200),
            1,
            cv2.LINE_AA,
        )

        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            is_recognized = det["is_recognized"]
            name = det.get("name", "Unknown Visitor")
            role = det.get("role", "Unknown")
            conf = det.get("conf", 0.0)
            duration = det.get("duration", 0.0)

            if is_recognized:
                # Emerald Green HUD for recognized family/residents
                color = (40, 210, 80)
                label = f"{name.upper()} [{role}] {int(conf * 100)}%"
            else:
                # Yellow/Red depending on loitering duration
                if duration > settings.LOITERING_ALERT_THRESHOLD_SEC:
                    color = (40, 40, 235)  # Crimson Alert
                    label = f"ALERT: LOITERING ({duration:.1f}s)"
                else:
                    color = (40, 180, 245)  # Amber Caution
                    label = f"VISITOR ({duration:.1f}s)"

            # Tactical Corner Reticle
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 1)
            corner_len = min(20, (x2 - x1) // 4, (y2 - y1) // 4)
            # Top-left
            cv2.line(annotated, (x1, y1), (x1 + corner_len, y1), color, 3)
            cv2.line(annotated, (x1, y1), (x1, y1 + corner_len), color, 3)
            # Top-right
            cv2.line(annotated, (x2, y1), (x2 - corner_len, y1), color, 3)
            cv2.line(annotated, (x2, y1), (x2, y1 + corner_len), color, 3)
            # Bottom-left
            cv2.line(annotated, (x1, y2), (x1 + corner_len, y2), color, 3)
            cv2.line(annotated, (x1, y2), (x1, y2 - corner_len), color, 3)
            # Bottom-right
            cv2.line(annotated, (x2, y2), (x2 - corner_len, y2), color, 3)
            cv2.line(annotated, (x2, y2), (x2, y2 - corner_len), color, 3)

            # Badge background
            badge_y = max(15, y1 - 10)
            (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(annotated, (x1, badge_y - text_h - 6), (x1 + text_w + 10, badge_y + 4), (20, 24, 30), -1)
            cv2.rectangle(annotated, (x1, badge_y - text_h - 6), (x1 + text_w + 10, badge_y + 4), color, 1)
            cv2.putText(
                annotated,
                label,
                (x1 + 5, badge_y - 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
                cv2.LINE_AA,
            )

        return annotated

    # ========================================================================
    # Decoupled Inference Loop (10 - 15 Hz)
    # ========================================================================

    def _worker_loop(self) -> None:
        """
        Continuous inference worker thread. Runs at target ~12 FPS.
        """
        logger.info("RTX 5060 Inference Worker Thread successfully started.")
        target_interval = 1.0 / settings.INFERENCE_FPS

        while self.is_running:
            loop_start = time.time()

            # 1. Fetch latest raw frame from ring buffer
            frame, ts = frame_buffer.wait_for_new_raw_frame(timeout=0.08)
            if frame is None:
                continue

            try:
                detections = []
                now = time.time()

                # Stage 1: Person Detection
                person_boxes = []
                if self.yolo_model is not None:
                    # Run YOLOv11 inference on CUDA
                    results = self.yolo_model.predict(
                        frame,
                        classes=[0],  # Class 0 = Person
                        conf=settings.YOLO_CONF_THRESHOLD,
                        device=0 if "cuda" in self.device else "cpu",
                        verbose=False,
                    )
                    for r in results:
                        for box in r.boxes:
                            xyxy = box.xyxy[0].cpu().numpy().astype(int)
                            person_boxes.append((xyxy[0], xyxy[1], xyxy[2], xyxy[3]))
                else:
                    # Fallback face/person detection heuristic (e.g. Haar or full frame center)
                    h, w, _ = frame.shape
                    # Detect center if insightface finds faces
                    pass

                # Stage 2: Face Recognition via InsightFace
                face_results = []
                if self.face_app is not None:
                    try:
                        faces = self.face_app.get(frame)
                        for f in faces:
                            bbox = f.bbox.astype(int)
                            emb = f.embedding
                            face_results.append((bbox, emb))
                    except Exception as e:
                        logger.debug(f"InsightFace processing warning: {e}")

                # Associate faces with person boxes or use face bounding boxes directly
                active_detections = []
                if face_results:
                    for bbox, emb in face_results:
                        name, role, conf = self.match_face(emb)
                        active_detections.append({
                            "bbox": (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
                            "name": name,
                            "role": role,
                            "conf": conf,
                            "is_recognized": name is not None,
                        })
                elif person_boxes:
                    for box in person_boxes:
                        active_detections.append({
                            "bbox": box,
                            "name": None,
                            "role": None,
                            "conf": 0.0,
                            "is_recognized": False,
                        })

                # Simple Spatial-Temporal Tracker for Loitering
                current_active_ids = []
                for det in active_detections:
                    bx1, by1, bx2, by2 = det["bbox"]
                    cx, cy = (bx1 + bx2) // 2, (by1 + by2) // 2

                    # Match with closest existing tracked person
                    best_tid = None
                    best_dist = 120.0  # pixel distance threshold

                    for tid, tinfo in list(self.tracked_persons.items()):
                        tcx, tcy = tinfo["centroid"]
                        dist = math.hypot(cx - tcx, cy - tcy)
                        if dist < best_dist:
                            best_dist = dist
                            best_tid = tid

                    if best_tid is None:
                        # New person appeared
                        best_tid = self.next_track_id
                        self.next_track_id += 1
                        self.tracked_persons[best_tid] = {
                            "first_seen": now,
                            "last_seen": now,
                            "centroid": (cx, cy),
                            "bbox": det["bbox"],
                            "alerted": False,
                        }

                    tinfo = self.tracked_persons[best_tid]
                    tinfo["last_seen"] = now
                    tinfo["centroid"] = (cx, cy)
                    tinfo["bbox"] = det["bbox"]
                    current_active_ids.append(best_tid)

                    duration = now - tinfo["first_seen"]
                    det["duration"] = duration

                    # Handle Recognized Resident Greeting
                    if det["is_recognized"]:
                        resident_name = det["name"]
                        last_greet = self.greeting_history.get(resident_name, 0.0)
                        if now - last_greet > settings.GREETING_COOLDOWN_SEC:
                            self.greeting_history[resident_name] = now
                            logger.info(f">>> RECOGNIZED RESIDENT: {resident_name} [{det['role']}]! <<<")

                            # Send UI state to phone screen (0x05)
                            if self.loop and self.loop.is_running():
                                asyncio.run_coroutine_threadsafe(
                                    sbmp_server.send_ui_state_to_phone({
                                        "action": "DISPLAY_GREETING",
                                        "title": "WELCOME HOME",
                                        "name": resident_name,
                                        "role": det["role"],
                                        "duration_sec": 6,
                                    }),
                                    self.loop,
                                )
                                # Personalized Edge-TTS Voice Greeting
                                custom_greeting = f"Welcome home, {resident_name}!"
                                # Check if custom greeting is in DB
                                for ef in self.enrolled_faces:
                                    if ef["name"] == resident_name and ef.get("custom_greeting"):
                                        custom_greeting = ef["custom_greeting"]
                                        break
                                asyncio.run_coroutine_threadsafe(
                                    self.speak_greeting_on_phone(custom_greeting),
                                    self.loop,
                                )

                    # Handle Unknown Visitor Loitering Alert (> 3.0s)
                    elif not det["is_recognized"] and duration >= self.loitering_threshold:
                        if not tinfo["alerted"]:
                            tinfo["alerted"] = True
                            self.trigger_intruder_alert(frame, duration, best_tid)

                    detections.append(det)

                # Clean up stale tracks (not seen for > 2 seconds)
                stale_ids = [tid for tid, t in self.tracked_persons.items() if now - t["last_seen"] > 2.0]
                for sid in stale_ids:
                    del self.tracked_persons[sid]

                # Update FPS calculation
                elapsed = time.time() - loop_start
                self.inference_times.append(elapsed)
                if len(self.inference_times) > 20:
                    self.inference_times.pop(0)
                avg_time = sum(self.inference_times) / len(self.inference_times)
                self.inference_fps = 1.0 / max(avg_time, 0.001)

                # Draw HUD and push to ring buffer
                annotated_frame = self.draw_hud(frame, detections, self.inference_fps)

                # Pre-compress JPEG for fast WebSocket delivery
                _, jpeg_bytes = cv2.imencode(".jpg", annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                frame_buffer.push_annotated_frame(
                    frame=annotated_frame,
                    jpeg_bytes=jpeg_bytes.tobytes(),
                    detections={"detections": detections, "count": len(detections)},
                    timestamp_ms=ts,
                )

            except Exception as e:
                logger.error(f"Error in RTX 5060 inference worker loop: {e}", exc_info=True)

            # Sleep to maintain 10-15 Hz rate
            time_spent = time.time() - loop_start
            sleep_needed = target_interval - time_spent
            if sleep_needed > 0:
                time.sleep(sleep_needed)

    def start(self) -> None:
        """Start the GPU AI pipeline worker thread."""
        if self.is_running:
            return
        self.is_running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, name="RTX5060-Worker", daemon=True)
        self.worker_thread.start()
        logger.info("GPUPipeline background thread launched.")

    def stop(self) -> None:
        """Stop worker thread."""
        self.is_running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)
            logger.info("GPUPipeline worker thread stopped.")


# Global singleton instance
gpu_pipeline = GPUPipeline()
