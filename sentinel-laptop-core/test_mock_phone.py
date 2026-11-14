"""
Sentinel Laptop Core - Mock Android Doorbell Phone Simulator
Simulates a physical Android device connecting to localhost:9000 over SBMP.
Emits 30 FPS video (0x01), 16kHz PCM audio (0x02), OS notifications & screen mirror (0x03),
doorbell rings & voice notes (0x06), and prints host intercom (0x04) and UI state (0x05).
"""

import sys
import time
import math
import json
import struct
import socket
import asyncio
import argparse
from pathlib import Path
import numpy as np
import cv2

# SBMP Channels
CH_VIDEO_H264 = 0x01
CH_MIC_AUDIO = 0x02
CH_PHONE_SCREEN = 0x03
CH_HOST_AUDIO = 0x04
CH_HOST_UI = 0x05
CH_TELEMETRY = 0x06


def pack_sbmp_frame(channel_id: int, payload: bytes) -> bytes:
    """Format an SBMP 9-byte header + binary payload."""
    timestamp_ms = int(time.time() * 1000) & 0xFFFFFFFF
    header = struct.pack(">BII", channel_id, timestamp_ms, len(payload))
    return header + payload


def generate_simulated_camera_frame(t: float, visitor_state: str = "resident") -> bytes:
    """
    Generate an animated 640x360 synthetic doorway camera feed with moving visitors.
    """
    w, h = 640, 360
    frame = np.zeros((h, w, 3), dtype=np.uint8)

    # Background: Porch lighting gradient
    for y in range(h):
        shade = int(24 + (y / h) * 35)
        frame[y, :, :] = (shade, int(shade * 1.1), int(shade * 1.2))

    # Doorframe & Wall
    cv2.rectangle(frame, (100, 40), (540, 360), (45, 52, 65), -1)
    cv2.rectangle(frame, (120, 60), (520, 360), (30, 35, 45), -1)
    cv2.line(frame, (320, 60), (320, 360), (20, 24, 30), 2)

    # Simulated Visitor Moving in Frame
    pos_x = int(320 + math.sin(t * 1.5) * 80)
    pos_y = int(200 + math.cos(t * 1.5) * 15)

    if visitor_state == "resident":
        body_color = (40, 180, 80)
        face_color = (200, 190, 180)
        name_tag = "SIMULATED RESIDENT (Dushyant)"
    else:
        body_color = (50, 60, 180)
        face_color = (180, 170, 160)
        name_tag = "SIMULATED VISITOR"

    # Head & Body
    cv2.circle(frame, (pos_x, pos_y - 45), 32, face_color, -1)
    cv2.ellipse(frame, (pos_x, pos_y + 40), (55, 60), 0, 0, 180, body_color, -1)
    # Eyes
    cv2.circle(frame, (pos_x - 10, pos_y - 48), 4, (40, 30, 20), -1)
    cv2.circle(frame, (pos_x + 10, pos_y - 48), 4, (40, 30, 20), -1)

    # Overlay metadata
    cv2.putText(frame, f"PHONE CAMERA SIMULATOR [CH 0x01] - {name_tag}", (15, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 230, 153), 1, cv2.LINE_AA)
    cv2.putText(frame, f"T={t:.2f}s | 30 FPS SIMULATED", (15, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 180, 200), 1, cv2.LINE_AA)

    # Encode as JPEG
    _, enc = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    return enc.tobytes()


def generate_kiosk_screen_frame(t: float) -> bytes:
    """Generate simulated Android Phone Kiosk UI display (Channel 0x03)."""
    w, h = 360, 640
    screen = np.zeros((h, w, 3), dtype=np.uint8)
    screen[:] = (20, 24, 32)

    # Top Status Bar
    cv2.rectangle(screen, (0, 0), (w, 30), (12, 14, 20), -1)
    cv2.putText(screen, "9:41 AM", (15, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    cv2.putText(screen, "88% [⚡]", (w - 75, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 230, 153), 1)

    # Doorbell Kiosk Card
    cv2.rectangle(screen, (30, 120), (w - 30, 480), (32, 40, 56), -1)
    cv2.rectangle(screen, (30, 120), (w - 30, 480), (0, 230, 153), 2)
    cv2.putText(screen, "SMART DOORBELL", (60, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
    cv2.putText(screen, "TOUCH TO RING", (90, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 230, 153), 1)

    # Pulse button
    btn_r = int(45 + math.sin(t * 3.0) * 5)
    cv2.circle(screen, (w // 2, 350), btn_r, (0, 230, 153), -1)
    cv2.circle(screen, (w // 2, 350), btn_r, (255, 255, 255), 2)

    _, enc = cv2.imencode(".jpg", screen, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    return enc.tobytes()


def generate_pcm_audio_chunk(sample_rate: int = 16000, duration: float = 0.1) -> bytes:
    """Generate 16kHz 16-bit Mono PCM audio (room tone / ambient noise)."""
    n_samples = int(sample_rate * duration)
    # Subtle ambient noise + soft tone
    noise = np.random.normal(0, 200, n_samples).astype(np.int16)
    return noise.tobytes()


async def run_mock_phone(host: str = "127.0.0.1", port: int = 9000, duration: float = 60.0):
    print("=" * 70)
    print("SENTINEL AI - MOCK ANDROID DOORBELL PHONE CLIENT")
    print(f"Connecting to host SBMP Server at {host}:{port}...")
    print("=" * 70)

    try:
        reader, writer = await asyncio.open_connection(host, port)
        print("[CONNECTED] Successfully established SBMP TCP session on port 9000!")
    except Exception as e:
        print(f"[ERROR] Could not connect to {host}:{port}: {e}")
        print("Make sure run_sentinel.py is running first!")
        return

    # Task 1: Receiver for Host Downstream Commands (0x04 Audio & 0x05 UI)
    async def downstream_listener():
        try:
            while True:
                hdr = await reader.readexactly(9)
                ch_id, ts, plen = struct.unpack(">BII", hdr)
                payload = await reader.readexactly(plen)

                if ch_id == CH_HOST_AUDIO:
                    print(f"\n[PHONE SPEAKER <- HOST 0x04] Received {len(payload)} bytes of audio (Intercom / Edge-TTS)!")
                elif ch_id == CH_HOST_UI:
                    data = json.loads(payload.decode("utf-8", errors="ignore"))
                    print(f"\n[PHONE SCREEN <- HOST 0x05] Received UI State: {data}")
                else:
                    print(f"\n[PHONE <- HOST 0x{ch_id:02X}] Received {plen} bytes.")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[LISTENER ERROR] {e}")

    listener_task = asyncio.create_task(downstream_listener())

    # Task 2: Transmitter for 30 FPS Video, Audio, Telemetry, and Simulated Triggers
    start_time = time.time()
    frame_interval = 1.0 / 30.0  # 30 FPS
    last_audio_time = 0.0
    last_screen_time = 0.0
    last_telem_time = 0.0

    doorbell_rung = False
    notification_sent = False
    voice_note_started = False
    voice_note_ended = False

    try:
        while time.time() - start_time < duration:
            t = time.time() - start_time

            # 1. Send Channel 0x01: 30 FPS Video Frame
            vid_bytes = generate_simulated_camera_frame(t, visitor_state="resident" if t < 8.0 else "unknown")
            writer.write(pack_sbmp_frame(CH_VIDEO_H264, vid_bytes))

            # 2. Send Channel 0x02: 16kHz PCM Audio (every 100ms)
            if t - last_audio_time >= 0.1:
                audio_bytes = generate_pcm_audio_chunk(16000, 0.1)
                writer.write(pack_sbmp_frame(CH_MIC_AUDIO, audio_bytes))
                last_audio_time = t

            # 3. Send Channel 0x03: Phone Kiosk Screen Mirror (every 500ms)
            if t - last_screen_time >= 0.5:
                kiosk_bytes = generate_kiosk_screen_frame(t)
                writer.write(pack_sbmp_frame(CH_PHONE_SCREEN, kiosk_bytes))
                last_screen_time = t

            # 4. Send Channel 0x06: Phone Battery Telemetry (every 4 seconds)
            if t - last_telem_time >= 4.0:
                telem_json = json.dumps({
                    "event": "TELEMETRY",
                    "battery_pct": int(85 - (t / 10)),
                    "is_charging": True,
                    "temp_c": round(31.0 + math.sin(t) * 1.5, 1),
                }).encode("utf-8")
                writer.write(pack_sbmp_frame(CH_TELEMETRY, telem_json))
                last_telem_time = t

            # 5. Simulated Event at T=3s: Intercepted Android OS Notification (Channel 0x03)
            if t > 3.0 and not notification_sent:
                notif_json = json.dumps({
                    "packageName": "com.whatsapp",
                    "title": "Amazon Delivery Agent",
                    "text": "Your package is arriving at the front door.",
                    "postTime": int(time.time() * 1000),
                }).encode("utf-8")
                writer.write(pack_sbmp_frame(CH_PHONE_SCREEN, notif_json))
                print("\n[MOCK PHONE -> HOST] Sent Intercepted Android OS Notification (com.whatsapp)!")
                notification_sent = True

            # 6. Simulated Event at T=6s: Doorbell Ring (Channel 0x06)
            if t > 6.0 and not doorbell_rung:
                ring_json = json.dumps({"event": "DOORBELL_RING"}).encode("utf-8")
                writer.write(pack_sbmp_frame(CH_TELEMETRY, ring_json))
                print("\n[MOCK PHONE -> HOST] Sent DOORBELL_RING Trigger!")
                doorbell_rung = True

            # 7. Simulated Event at T=10s: Voice Note Start (Channel 0x06)
            if t > 10.0 and not voice_note_started:
                vn_start = json.dumps({"event": "VOICE_NOTE_START"}).encode("utf-8")
                writer.write(pack_sbmp_frame(CH_TELEMETRY, vn_start))
                print("\n[MOCK PHONE -> HOST] Sent VOICE_NOTE_START Trigger!")
                voice_note_started = True

            # 8. Simulated Event at T=13s: Voice Note End (Channel 0x06)
            if t > 13.0 and not voice_note_ended:
                vn_end = json.dumps({"event": "VOICE_NOTE_END"}).encode("utf-8")
                writer.write(pack_sbmp_frame(CH_TELEMETRY, vn_end))
                print("\n[MOCK PHONE -> HOST] Sent VOICE_NOTE_END Trigger (whisper will transcribe)!")
                voice_note_ended = True

            await writer.drain()
            await asyncio.sleep(frame_interval)

    except KeyboardInterrupt:
        print("\nStopping mock phone client...")
    finally:
        listener_task.cancel()
        writer.close()
        await writer.wait_closed()
        print("Mock phone client terminated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sentinel Mock Android Doorbell Phone Simulator")
    parser.add_argument("--host", default="127.0.0.1", help="Host IP address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9000, help="SBMP Port (default: 9000)")
    parser.add_argument("--duration", type=float, default=120.0, help="Simulation duration in seconds")
    args = parser.parse_args()

    asyncio.run(run_mock_phone(host=args.host, port=args.port, duration=args.duration))
