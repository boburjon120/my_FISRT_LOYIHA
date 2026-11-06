"""MP3 conversion with the real FFmpeg binary (no network)."""

import json
import shutil
import subprocess
from dataclasses import replace

import pytest

from audio_service import AudioService, convert_to_mp3, fitting_bitrate, make_telegram_thumbnail
from tests.conftest import FakeYouTube
from utils.errors import FileTooLargeError, PermanentError
from youtube_service import VideoInfo

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def make_tone(path, seconds=3):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", str(path)],
        check=True,
    )


def make_image(path):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=0x6a00ff:s=480x360", "-frames:v", "1", str(path)],
        check=True,
    )


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


async def test_convert_to_mp3_192k_with_metadata(tmp_path):
    src = tmp_path / "source.m4a"
    make_tone(src)
    cover = tmp_path / "cover.jpg"
    make_image(cover)
    target = tmp_path / "Qo'shiq nomi.mp3"
    await convert_to_mp3(src, target, bitrate_kbps=192, title="Qo'shiq nomi", artist="AURIX", cover=cover)
    data = probe(target)
    audio = [s for s in data["streams"] if s["codec_type"] == "audio"][0]
    assert audio["codec_name"] == "mp3"
    assert int(audio["bit_rate"]) == 192000
    assert data["format"]["tags"]["title"] == "Qo'shiq nomi"
    assert data["format"]["tags"]["artist"] == "AURIX"
    assert any(s["codec_type"] == "video" for s in data["streams"])  # embedded cover


async def test_convert_broken_cover_falls_back(tmp_path):
    src = tmp_path / "source.m4a"
    make_tone(src, 1)
    bad_cover = tmp_path / "cover.jpg"
    bad_cover.write_bytes(b"not an image")
    target = tmp_path / "out.mp3"
    await convert_to_mp3(src, target, bitrate_kbps=128, cover=bad_cover)
    assert target.stat().st_size > 0


async def test_telegram_thumbnail(tmp_path):
    src = tmp_path / "cover.jpg"
    make_image(src)
    thumb = await make_telegram_thumbnail(src, tmp_path / "thumb.jpg")
    stream = probe(thumb)["streams"][0]
    assert (stream["width"], stream["height"]) == (320, 320)


def test_fitting_bitrate():
    limit = 50 * 1024 * 1024
    assert fitting_bitrate(600, limit, 192, 64) == 192          # 10 min
    assert fitting_bitrate(3 * 3600, limit, 192, 32) == 32      # 3 h with low minimum
    assert fitting_bitrate(45 * 60, limit, 192, 64) == 128      # 45 min
    assert fitting_bitrate(4 * 3600, limit, 192, 64) is None    # cannot fit
    assert fitting_bitrate(None, limit, 192, 64) == 192


def _info(duration=3, title="Mening qo'shig'im / remix"):
    return VideoInfo("AAAAAAAAAAA", title, "https://www.youtube.com/watch?v=AAAAAAAAAAA",
                     duration, "", "Test Channel", None)


async def test_create_mp3_pipeline(settings, tmp_path, monkeypatch):
    service = AudioService(settings, FakeYouTube())

    def fake_download(raw_info, workdir, *args):
        src = workdir / "source.m4a"
        make_tone(src)
        return src

    monkeypatch.setattr(service, "_download_source_sync", fake_download)
    workdir = tmp_path / "job"
    result = await service.create_mp3(_info(), {}, workdir, max_duration_minutes=60)
    assert result.filename == "Mening qo'shig'im remix.mp3"
    assert result.path.exists() and result.bitrate_kbps == 192
    assert not (workdir / "source.m4a").exists()  # source removed after conversion


async def test_create_mp3_rejects_too_long(settings, tmp_path):
    service = AudioService(settings, FakeYouTube())
    with pytest.raises(PermanentError):
        await service.create_mp3(_info(duration=7200), {}, tmp_path, max_duration_minutes=60)


async def test_create_mp3_rejects_unfittable(settings, tmp_path, monkeypatch):
    settings = replace(settings, upload_limit_mb=1)
    service = AudioService(settings, FakeYouTube())
    monkeypatch.setattr(service, "_download_source_sync", lambda raw, wd, *a: (wd / "source.m4a"))
    with pytest.raises(FileTooLargeError):
        await service.create_mp3(_info(duration=3600), {}, tmp_path / "j", max_duration_minutes=120)
