"""/health endpoint used by Render and uptime pingers."""

import asyncio

import aiohttp

from monitor import ChannelMonitor
from queue_worker import QueueWorker
from tests.conftest import FakeAudio, FakePublisher, FakeYouTube
from web_server import HealthServer


async def test_health_endpoint(settings, db):
    worker = QueueWorker(settings, db, FakeYouTube(), FakeAudio(), FakePublisher(), asyncio.Semaphore(1))
    monitor = ChannelMonitor(settings, db, FakeYouTube())
    server = HealthServer(monitor, worker, port=0, host="127.0.0.1")
    await server.start()
    try:
        port = server._runner.addresses[0][1]
        async with aiohttp.ClientSession() as session:
            for path in ("/", "/health"):
                async with session.get(f"http://127.0.0.1:{port}{path}") as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["status"] == "ok"
                    assert data["monitor_running"] is False
                    assert "token" not in str(data).lower()
    finally:
        await server.stop()
