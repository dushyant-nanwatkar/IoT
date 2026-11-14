"""
Sentinel Laptop Core - Unified Orchestration Entry Point
Boots SBMP TCP Port 9000, Persistent ADB Tunnel Healer, RTX 5060 AI Pipeline,
and FastAPI + 30 FPS WebSocket Server on Port 8000.
"""

import sys
import os
import time
import signal
import asyncio
import logging
import uvicorn
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings
from database import init_db, load_all_enrolled_embeddings, engine
from sbmp_server import sbmp_server
from gpu_pipeline import gpu_pipeline
from cloud_sync import cloud_sync_queue
from main import app, stream_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sentinel.core")


def print_banner():
    banner = f"""
================================================================================
   ____ _____ _   _ _____ ___ _   _ _____ _          _    ___ 
  / ___| ____| \ | |_   _|_ _| \ | | ____| |        / \  |_ _|
  \___ \  _| |  \| | | |  | ||  \| |  _| | |       / _ \  | | 
   ___) | |__| |\  | | |  | || |\  | |___| |___   / ___ \ | | 
  |____/|_____|_| \_| |_| |___|_| \_|_____|_____| /_/   \_\___|
  
  AUTONOMOUS EDGE DOORBELL ARCHITECTURE • HOST CORE SERVER
================================================================================
  [TARGET PLATFORM]   Lenovo Legion / LOQ
  [HOST CPU]          AMD Ryzen 7 250 (High-Concurrency Async I/O)
  [HOST RAM]          32GB DDR5 System Memory
  [ACCELERATOR]       NVIDIA GeForce RTX 5060 (8GB VRAM)
  [SBMP PROTOCOL]     TCP Port 9000 (Demuxer & H.264 PyAV)
  [ADB AUTO-HEAL]     adb reverse tcp:{settings.ADB_REVERSE_REMOTE} tcp:{settings.ADB_REVERSE_LOCAL} (Every 5s)
  [HOMEOWNER SERVER]  FastAPI + WebSocket @ http://0.0.0.0:{settings.API_PORT}
  [DATABASE]          Async SQLite + SQLAlchemy Auto-Migration
  [AI MODELS]         YOLOv11 Person Track, InsightFace Buffalo_L, Whisper, Edge-TTS
================================================================================
"""
    print(banner)


async def main():
    print_banner()
    loop = asyncio.get_running_loop()
    gpu_pipeline.set_event_loop(loop)

    # 1. Database Init & Auto-Migration
    logger.info("Step 1/6: Initializing SQLite database...")
    await init_db()

    # 2. Load Enrolled Faces into GPU Cosine Cache
    logger.info("Step 2/6: Loading enrolled face embeddings into GPU memory...")
    enrolled_faces = await load_all_enrolled_embeddings()
    gpu_pipeline.refresh_enrolled_faces(enrolled_faces)

    # 3. Initialize AI Models on RTX 5060
    logger.info("Step 3/6: Loading neural models on NVIDIA RTX 5060...")
    gpu_pipeline.initialize_models()

    # Wire Whisper transcription callback into SBMP server
    sbmp_server.set_transcription_handler(gpu_pipeline.transcribe_audio_file)

    # 4. Start SBMP TCP Server on Port 9000 & ADB Tunnel Healer
    logger.info("Step 4/6: Launching SBMP TCP Listener on 0.0.0.0:9000...")
    await sbmp_server.start()

    # 5. Start Decoupled GPU AI Pipeline & Cloud Sync Queue
    logger.info("Step 5/6: Launching decoupled RTX 5060 AI worker thread (10-15 Hz)...")
    gpu_pipeline.start()
    await cloud_sync_queue.start()

    # 6. Start 30 FPS WebSocket Broadcaster
    logger.info("Step 6/6: Starting 30 FPS Client Stream Broadcaster...")
    stream_manager.start()

    logger.info("=" * 70)
    logger.info(f"Sentinel Core Backend successfully running!")
    logger.info(f"Open Homeowner Dashboard in your browser: http://localhost:{settings.API_PORT}/")
    logger.info(f"API Docs available at: http://localhost:{settings.API_PORT}/docs")
    logger.info("=" * 70)

    # Configure Uvicorn server
    config = uvicorn.Config(
        app=app,
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    # Handle graceful shutdown
    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received. Initiating graceful shutdown...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows signal handling workaround
            pass

    server_task = asyncio.create_task(server.serve())

    try:
        await server_task
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        logger.info("Cleaning up server resources...")
        stream_manager.stop()
        await sbmp_server.stop()
        gpu_pipeline.stop()
        await cloud_sync_queue.stop()
        await engine.dispose()
        logger.info("Sentinel Core cleanly shutdown.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user. Exiting.")
