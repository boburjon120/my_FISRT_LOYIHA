"""Exercise the real yt-dlp download code path against a local HTTP server.

The metadata dict mimics what yt-dlp returns for a YouTube video, but the
format URLs point to 127.0.0.1, so no YouTube access is needed.
"""

import functools
import http.server
import shutil
import subprocess
import threading

import pytest

from audio_service import AudioService
from video_service import VideoService
from youtube_service import VideoInfo, YouTubeService

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture
def media_server(tmp_path):
    root = tmp_path / "www"
    root.mkdir()
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=2",
                    "-c:a", "aac", str(root / "a.m4a")], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:d=2",
                    "-f", "lavfi", "-i", "sine=f=440:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(root / "v.mp4")], check=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def raw_info(base):
    return {
        "id": "AAAAAAAAAAA", "title": "Local test", "extractor": "youtube", "extractor_key": "Youtube",
        "webpage_url": "https://www.youtube.com/watch?v=AAAAAAAAAAA", "duration": 2,
        "formats": [
            {"format_id": "140", "url": f"{base}/a.m4a", "ext": "m4a", "vcodec": "none",
             "acodec": "mp4a.40.2", "abr": 128, "protocol": "http"},
            {"format_id": "18", "url": f"{base}/v.mp4", "ext": "mp4", "vcodec": "avc1.42001E",
             "acodec": "mp4a.40.2", "height": 240, "width": 320, "protocol": "http"},
        ],
    }


class LocalYouTube(YouTubeService):
    def base_opts(self):
        return super().base_opts() | {"proxy": ""}

    async def download_thumbnail(self, video_id, dest):
        return False


INFO = VideoInfo("AAAAAAAAAAA", "Local / test", "https://www.youtube.com/watch?v=AAAAAAAAAAA",
                 2, "", "Tester", None)


async def test_real_ytdlp_audio_download_and_mp3(settings, media_server, tmp_path):
    service = AudioService(settings, LocalYouTube(settings))
    result = await service.create_mp3(INFO, raw_info(media_server), tmp_path / "job", max_duration_minutes=10)
    assert result.filename == "Local test.mp3"
    assert result.path.exists() and result.size > 1000


async def test_real_ytdlp_video_download(settings, media_server, tmp_path):
    service = VideoService(settings, LocalYouTube(settings))
    result = await service.create_mp4(INFO, raw_info(media_server), tmp_path / "job", max_duration_minutes=10)
    assert result.filename == "Local test.mp4"
    assert (result.width, result.video_height) == (320, 240)


def test_ensure_allowed_rejects_restricted():
    from utils.errors import NotReadyError, PermanentError

    for info, err in [
        ({"availability": "private"}, PermanentError),
        ({"availability": "subscriber_only"}, PermanentError),
        ({"availability": "needs_auth"}, PermanentError),
        ({"age_limit": 18}, PermanentError),
        ({"formats": [{"has_drm": True}]}, PermanentError),
        ({"live_status": "is_upcoming"}, NotReadyError),
        ({"live_status": "is_live"}, NotReadyError),
    ]:
        with pytest.raises(err):
            YouTubeService.ensure_allowed(info)
    YouTubeService.ensure_allowed({"availability": "public", "live_status": "not_live"})


def test_classify_ytdlp_errors():
    from utils.errors import NotReadyError, PermanentError, TransientError
    from youtube_service import classify_ytdlp_error

    assert isinstance(classify_ytdlp_error(Exception("ERROR: [youtube] x: Private video")), PermanentError)
    assert isinstance(classify_ytdlp_error(Exception("Video unavailable")), PermanentError)
    assert isinstance(classify_ytdlp_error(Exception("Sign in to confirm your age")), PermanentError)
    assert isinstance(classify_ytdlp_error(Exception("Premieres in 3 hours")), NotReadyError)
    err = classify_ytdlp_error(Exception("Sign in to confirm you're not a bot"))
    assert type(err) is TransientError
    assert type(classify_ytdlp_error(Exception("Connection reset by peer"))) is TransientError


async def test_real_ytdlp_instagram_mp4(settings, media_server, tmp_path):
    from dataclasses import replace as dc_replace

    info = dc_replace(INFO, platform="instagram", video_id="C9abcDEF123")
    raw = raw_info(media_server) | {"extractor": "Instagram", "extractor_key": "Instagram", "id": "C9abcDEF123"}
    service = VideoService(settings, LocalYouTube(settings), LocalYouTube(settings))
    result = await service.create_mp4(info, raw, tmp_path / "ig", max_duration_minutes=10)
    assert result.filename == "Local test.mp4"
    assert (result.width, result.video_height) == (320, 240)
