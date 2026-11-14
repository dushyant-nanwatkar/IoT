"""
Sentinel Laptop Core - Cloud Sync Manager (Supabase Storage & Postgres)
Asynchronous background sync queue for security events and intruder snapshots.
Gracefully operates in offline / local-first mode when cloud credentials are not supplied.
"""

import os
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from config import settings

logger = logging.getLogger("sentinel.cloud")

# Optional Supabase SDK
try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False
    Client = Any


class CloudSyncQueue:
    """
    Asynchronous event queue that offloads high-resolution intruder snapshots
    and critical security logs to Supabase Cloud Storage + Postgres.
    """

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.client: Optional[Client] = None
        self.is_running: bool = False
        self.worker_task: Optional[asyncio.Task] = None
        self.is_configured: bool = False

    def initialize_client(self) -> None:
        """Initialize the Supabase client if credentials are configured."""
        if not HAS_SUPABASE:
            logger.info("Supabase client package not installed; running in local-only mode.")
            return

        if settings.SUPABASE_URL and settings.SUPABASE_KEY:
            try:
                self.client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
                self.is_configured = True
                logger.info("Supabase Cloud Sync initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
                self.is_configured = False
        else:
            logger.info("Supabase credentials not configured in environment. Cloud sync disabled (local mode).")
            self.is_configured = False

    async def enqueue(
        self,
        event_id: int,
        event_type: str,
        severity: str,
        message: str,
        snapshot_file_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Queue a security event for cloud synchronization."""
        item = {
            "event_id": event_id,
            "event_type": event_type,
            "severity": severity,
            "message": message,
            "snapshot_path": snapshot_file_path,
            "metadata": metadata or {},
        }
        await self.queue.put(item)
        logger.debug(f"Queued event #{event_id} ({event_type}) for cloud sync.")

    async def _worker_loop(self) -> None:
        """Continuous worker that processes cloud sync queue items."""
        while self.is_running:
            try:
                item = await self.queue.get()
                if not self.is_configured or not self.client:
                    # Cloud not configured; mark processed locally
                    self.queue.task_done()
                    continue

                event_id = item["event_id"]
                snap_path = item.get("snapshot_path")
                cloud_snapshot_url = None

                # 1. Upload snapshot to Supabase Storage Bucket
                if snap_path and os.path.exists(snap_path):
                    try:
                        file_name = Path(snap_path).name
                        remote_path = f"snapshots/{file_name}"

                        with open(snap_path, "rb") as f:
                            file_bytes = f.read()

                        # Upload to bucket
                        res = self.client.storage.from_(settings.SUPABASE_BUCKET).upload(
                            remote_path,
                            file_bytes,
                            {"content-type": "image/jpeg"},
                        )
                        # Get Public URL
                        cloud_snapshot_url = self.client.storage.from_(settings.SUPABASE_BUCKET).get_public_url(remote_path)
                        logger.info(f"Uploaded snapshot to Supabase Storage: {cloud_snapshot_url}")
                    except Exception as upload_err:
                        logger.warning(f"Failed to upload snapshot to Supabase: {upload_err}")

                # 2. Insert event record into Supabase Postgres table `sentinel_events`
                try:
                    payload = {
                        "local_id": event_id,
                        "event_type": item["event_type"],
                        "severity": item["severity"],
                        "message": item["message"],
                        "snapshot_url": cloud_snapshot_url,
                        "metadata": item["metadata"],
                    }
                    self.client.table("sentinel_events").insert(payload).execute()
                    logger.info(f"Event #{event_id} successfully synced to Supabase Postgres.")
                except Exception as pg_err:
                    logger.warning(f"Failed to sync event #{event_id} to Supabase table: {pg_err}")

                self.queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in CloudSync worker: {e}")
                await asyncio.sleep(1.0)

    async def start(self) -> None:
        """Start the background sync worker."""
        self.is_running = True
        self.initialize_client()
        self.worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """Stop cloud sync worker."""
        self.is_running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass


# Global singleton instance
cloud_sync_queue = CloudSyncQueue()
