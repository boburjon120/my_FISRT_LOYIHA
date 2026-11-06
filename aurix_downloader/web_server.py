"""Tiny HTTP health server.

Hosting platforms such as Render (free "Web Service") require the app to
listen on ``$PORT`` and stop idle services. This server answers ``/`` and
``/health`` so the platform health check passes and an external pinger
(e.g. UptimeRobot every 5 minutes) keeps the bot awake. It exposes no
secrets: only on/off status and timestamps.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from monitor import ChannelMonitor
    from queue_worker import QueueWorker

log = logging.getLogger(__name__)


def create_app(monitor: "ChannelMonitor", worker: "QueueWorker") -> web.Application:
    async def health(_: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "service": "AURIX Downloader",
                "monitor_running": monitor.is_running,
                "worker_running": worker.is_running,
                "last_check_at": monitor.status.last_check_at,
                "last_success_at": monitor.status.last_success_at,
            }
        )

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    return app


class HealthServer:
    def __init__(self, monitor: "ChannelMonitor", worker: "QueueWorker", port: int, host: str = "0.0.0.0") -> None:
        self.app = create_app(monitor, worker)
        self.host = host
        self.port = port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.host, self.port).start()
        log.info("Health server listening on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
