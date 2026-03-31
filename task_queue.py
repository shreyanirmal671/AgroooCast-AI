from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from backend_database import SessionLocal, create_notification_delivery_log
from notify_engine import dispatch_custom_alert_notifications


@dataclass
class NotificationTask:
    farm_id: int
    farm_name: str
    custom_alerts: list[dict[str, Any]]
    channel_config: dict[str, Any]
    retries_left: int = 2


_TASK_QUEUE: queue.Queue[NotificationTask] = queue.Queue()
_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()


def _log_channels(farm_id: int, channels: list[dict[str, Any]]) -> None:
    if not channels:
        return

    db = SessionLocal()
    try:
        for item in channels:
            create_notification_delivery_log(
                db,
                farm_id=farm_id,
                channel=str(item.get("channel", "unknown")),
                status=str(item.get("status", "unknown")),
                detail=str(item.get("detail", "")),
            )
    finally:
        db.close()


def _worker_loop() -> None:
    while True:
        task = _TASK_QUEUE.get()
        try:
            report = dispatch_custom_alert_notifications(
                farm_name=task.farm_name,
                custom_alerts=task.custom_alerts,
                channel_config=task.channel_config,
            )
            _log_channels(task.farm_id, report.get("channels", []))

            has_failure = report.get("attempted", 0) > report.get("sent", 0)
            if has_failure and task.retries_left > 0:
                # Simple delayed retry policy for transient provider/API failures.
                time.sleep(3)
                _TASK_QUEUE.put(
                    NotificationTask(
                        farm_id=task.farm_id,
                        farm_name=task.farm_name,
                        custom_alerts=task.custom_alerts,
                        channel_config=task.channel_config,
                        retries_left=task.retries_left - 1,
                    )
                )
        except Exception as exc:
            db = SessionLocal()
            try:
                create_notification_delivery_log(
                    db,
                    farm_id=task.farm_id,
                    channel="system",
                    status="failed",
                    detail=f"Queue worker exception: {exc}",
                )
            finally:
                db.close()
        finally:
            _TASK_QUEUE.task_done()


def start_notification_worker() -> None:
    global _WORKER_STARTED
    # Start one daemon worker for queued dispatch jobs in-process.
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        thread = threading.Thread(target=_worker_loop, name="notification-worker", daemon=True)
        thread.start()
        _WORKER_STARTED = True


def enqueue_notification_task(task: NotificationTask) -> None:
    _TASK_QUEUE.put(task)
