# SENTINEL AI - Laptop Core Backend

Autonomous Edge Computer Vision & Multi-Channel Communications Host for Smart Doorbell Systems.

Designed for high-performance edge laptops featuring an **AMD Ryzen 7 250**, **32GB DDR5 RAM**, and an **NVIDIA GeForce RTX 5060 (8GB VRAM)**.

---

## 🏗️ Architecture Overview

Sentinel Laptop Core implements a **decoupled, multi-rate concurrency architecture**:
1. **Host-Side SBMP Demuxer (Port 9000):** Hardware H.264 NAL parsing in C via PyAV, streaming PCM audio, Android notification ingestion, and auto-healing ADB reverse tunneling.
2. **Decoupled RTX 5060 AI Worker (10–15 Hz):** Runs YOLOv11 person tracking, InsightFace Buffalo_L 512-D cosine matching, loitering threat detection, and Edge-TTS audio greeting synthesis.
3. **FastAPI & 30 FPS Multiplexed WebSocket (Port 8000):** Serves the Homeowner Client App with low-latency annotated video, two-way intercom audio, door controls, and real-time security logs.

```
+-------------------------------------------------------------------------------+
|                       ANDROID DOORBELL PHONE (KIOSK)                          |
|  - Camera2 H.264 NAL Stream (0x01)       - Doorbell Chimes & Telemetry (0x06) |
|  - 16kHz PCM Mic Audio (0x02)            - Screen Mirror & Notifications(0x03)|
|  - Speaker Playback (0x04)               - Dynamic UI Greeting Kiosk (0x05)   |
+-------------------------------------------------------------------------------+
                                    |  ▲
        `adb reverse tcp:9000 tcp:9000`|  |  TCP Port 9000 (Bridged USB/Wi-Fi)
                                    ▼  |
+-------------------------------------------------------------------------------+
|                     SENTINEL LAPTOP CORE HOST (PORT 9000)                     |
|  sbmp_server.py: 9-Byte Binary Header Demuxer [channel_id, ts_ms, payload_len]|
|  - Channel 0x01 -> PyAV CodecContext C-Decoder -> FrameRingBuffer (30 FPS)    |
|  - Channel 0x02 -> Intercom Broadcaster & Voice Note Buffer                   |
|  - Channel 0x03 -> Kiosk Screen Store & Android Notification Parser           |
|  - Channel 0x06 -> Doorbell Trigger, Whisper Dispatch & Telemetry Logger      |
|  - adb_tunnel_manager() -> Auto-heals tunnel every 5s                         |
+-------------------------------------------------------------------------------+
               |                                            ▲
      Decoupled Pull (10-15 Hz)                    HUD Overlay Push
               ▼                                            |
+-------------------------------------------------------------------------------+
|                 RTX 5060 DEDICATED AI WORKER (gpu_pipeline.py)                |
|  - Stage 1: YOLOv11 Person & Loitering Tracker (>3.0s -> INTRUDER_ALERT)     |
|  - Stage 2: InsightFace Buffalo_L (512-D Normalized Cosine Match >= 0.48)     |
|  - Stage 3: Edge-TTS Neural Voice Greeting -> Streamed via 0x04 to Phone      |
|  - Stage 4: Faster-Whisper (CUDA float16) Voice Note Transcription            |
+-------------------------------------------------------------------------------+
               |
         Synced via WebSocket & REST
               ▼
+-------------------------------------------------------------------------------+
|                HOMEOWNER CLIENT APP / WEB DASHBOARD (PORT 8000)               |
|  - WS /ws/client-stream: 30 FPS HUD Camera, Kiosk Mirror, 2-Way Intercom      |
|  - REST Endpoints: Face Enrollment, Notices, Camera Control, Audit Logs       |
+-------------------------------------------------------------------------------+
```

---

## ⚡ SBMP (Sentinel Binary Multiplex Protocol) Specification

Every packet over TCP port `9000` is prefixed with a 9-byte big-endian header:
```
+---------------+-------------------+---------------------+
| Channel ID    | Timestamp (ms)    | Payload Length (B)  |
| 1 Byte (0-255)| 4 Bytes (uint32)  | 4 Bytes (uint32)    |
+---------------+-------------------+---------------------+
```
Header unpacking in Python: `channel_id, timestamp_ms, payload_len = struct.unpack(">BII", header_bytes)`

| Channel ID | Direction | Type | Description |
|---|---|---|---|
| `0x01` | Phone -> Host | Binary | Raw H.264 Annex-B NAL Units (or fallback JPEG/PNG) |
| `0x02` | Phone -> Host | Binary | Raw 16kHz 16-bit Mono PCM Mic Audio |
| `0x03` | Phone -> Host | JSON / Bin | Intercepted Android Notifications (JSON `{...}`) or Kiosk Display Mirror (JPEG) |
| `0x04` | Host -> Phone | Binary | Intercom & Neural TTS Audio Stream to Phone Speaker (16kHz PCM) |
| `0x05` | Host -> Phone | JSON | UI Display State (`DISPLAY_GREETING`, `DISPLAY_NOTICE`, `SWITCH_CAMERA`, `TRIGGER_SIREN`) |
| `0x06` | Phone -> Host | JSON | Doorbell Chime, Voice Note Start/Stop, and Battery Telemetry |

---

## 📦 Installation & Setup

### 1. Requirements
- Python 3.10+
- NVIDIA CUDA 12.x / 13.x with cuDNN
- Android platform-tools (`adb`) installed

### 2. Install Python Dependencies
```powershell
cd sentinel-laptop-core
pip install -r requirements.txt
```

### 3. Environment Configuration (Optional `.env`)
Create `.env` file in `sentinel-laptop-core/`:
```env
SBMP_PORT=9000
API_PORT=8000
DEVICE=cuda:0
YOLO_MODEL_NAME=yolo11n.pt
INSIGHTFACE_MODEL=buffalo_l
WHISPER_MODEL=small
FACE_MATCH_THRESHOLD=0.48
LOITERING_ALERT_THRESHOLD_SEC=3.0

# Optional Supabase Cloud Sync
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
```

---

## 🚀 Running the System

### 1. Start the Sentinel Core Server
```powershell
python run_sentinel.py
```
This will:
- Auto-migrate SQLite schema (`sentinel.db`).
- Load enrolled face embeddings into GPU memory.
- Initialize YOLOv11 and InsightFace Buffalo_L on the RTX 5060.
- Start the SBMP TCP Server on `0.0.0.0:9000`.
- Start the ADB reverse tunnel healer.
- Launch FastAPI + WebSocket Server on `http://0.0.0.0:8000`.

### 2. Open the Homeowner Command Center
Navigate in your browser to:
**[http://localhost:8000](http://localhost:8000)**

### 3. Simulate or Connect an Android Doorbell Phone
**Option A: Run the End-to-End Mock Phone Simulator (No hardware needed):**
```powershell
python test_mock_phone.py
```
*Simulates 30 FPS camera feed, moving visitors, 16kHz audio, WhatsApp notification interception, doorbell rings, and voice notes.*

**Option B: Connect a Physical Android Phone via USB:**
1. Enable **USB Debugging** on the Android device.
2. Plug the phone into the laptop via USB.
3. The built-in `adb_tunnel_manager` automatically runs `adb reverse tcp:9000 tcp:9000`.
4. Launch the Android Doorbell Kiosk app on the phone.

---

## 🔌 API Reference

### WebSocket Stream
- `WS /ws/client-stream`: Multiplexed bidirectional stream
  - Tag `0x01` (Binary): 30 FPS HUD Camera JPEG
  - Tag `0x02` (Binary): Doorway Mic 16kHz PCM Audio
  - Tag `0x03` (Binary): Phone Kiosk Mirror JPEG
  - Tag `0x04` (Binary): Homeowner Mic to Phone Speaker
  - JSON Text: Real-time security events, intruder alerts, toasts, and telemetry

### REST Endpoints
- `POST /api/faces/enroll`: Enroll resident (1-5 photos + Name + Role + Custom Greeting)
- `GET /api/faces`: List all enrolled residents
- `DELETE /api/faces/{id}`: Delete enrolled face
- `POST /api/kiosk/notice`: Push text notice to phone screen (+ optional Edge-TTS voice)
- `POST /api/camera/control`: Toggle Front/Back camera, trigger emergency siren, force snapshot
- `GET /api/events`: Filterable audit log of security events
- `GET /api/system/status`: Real-time GPU VRAM, FPS, ADB status, and Phone battery
