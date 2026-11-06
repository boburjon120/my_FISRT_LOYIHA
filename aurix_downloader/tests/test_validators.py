import pytest

from utils.text import safe_filename
from utils.validators import (
    canonical_video_url,
    extract_video_id,
    find_youtube_url,
    normalize_telegram_chat,
    parse_channel_input,
)

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VID}",
        f"https://youtube.com/watch?v={VID}&t=42s",
        f"http://m.youtube.com/watch?v={VID}",
        f"https://music.youtube.com/watch?v={VID}&list=RD",
        f"https://youtu.be/{VID}",
        f"https://youtu.be/{VID}?si=abc",
        f"youtu.be/{VID}",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/embed/{VID}",
        f"https://www.youtube.com/live/{VID}",
    ],
)
def test_valid_urls(url):
    assert extract_video_id(url) == VID


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
        "https://evil.com/?u=https://youtu.be/dQw4w9WgXcQ",
        "http://127.0.0.1/watch?v=dQw4w9WgXcQ",
        "http://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
        "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://user:pass@youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com:8080/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ%00",
        "https://www.youtube.com/playlist?list=PL123",
        "",
        "not a url",
    ],
)
def test_rejected_urls(url):
    assert extract_video_id(url) is None


def test_canonical_url_only_built_from_id():
    assert canonical_video_url(VID) == f"https://www.youtube.com/watch?v={VID}"
    with pytest.raises(ValueError):
        canonical_video_url("../../etc")


def test_find_url_in_text():
    assert find_youtube_url(f"Mana shu qo'shiq: (https://youtu.be/{VID}) zo'r") == VID
    assert find_youtube_url("salom") is None


def test_parse_channel_input():
    cid = "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert parse_channel_input(cid) == ("id", cid)
    assert parse_channel_input(f"https://www.youtube.com/channel/{cid}/videos") == ("id", cid)
    assert parse_channel_input("@GoogleDevelopers") == ("url", "https://www.youtube.com/@GoogleDevelopers")
    assert parse_channel_input("https://youtube.com/@GoogleDevelopers/videos") == (
        "url", "https://www.youtube.com/@GoogleDevelopers")
    assert parse_channel_input("https://evil.com/@GoogleDevelopers") is None
    assert parse_channel_input("hello world") is None


def test_normalize_telegram_chat():
    assert normalize_telegram_chat("@aurix_music") == "@aurix_music"
    assert normalize_telegram_chat("https://t.me/aurix_music") == "@aurix_music"
    assert normalize_telegram_chat("-1001234567890") == "-1001234567890"
    assert normalize_telegram_chat("drop table") is None


def test_safe_filename_keeps_title():
    assert safe_filename("Yulduz Usmonova - Qo'shiq", "mp3") == "Yulduz Usmonova - Qo'shiq.mp3"
    assert safe_filename("a/b\\c:d*e?f\"g<h>i|j", "mp3") == "a b c d e f g h i j.mp3"
    assert safe_filename("../../etc/passwd", "mp3") == "etc passwd.mp3"
    assert safe_filename("   ", "mp3") == "audio.mp3"
    assert len(safe_filename("x" * 500, "mp3")) <= 124


def test_cookies_file_is_copied_to_writable_location(settings, tmp_path):
    from dataclasses import replace

    from youtube_service import YouTubeService

    secret = tmp_path / "secrets" / "cookies.txt"
    secret.parent.mkdir()
    secret.write_text("# Netscape HTTP Cookie File\n")
    secret.chmod(0o400)
    yt = YouTubeService(replace(settings, ytdlp_cookies_file=str(secret)))
    path = yt.base_opts()["cookiefile"]
    assert path != str(secret)
    assert open(path).read().startswith("# Netscape")
    with open(path, "a") as fh:  # yt-dlp must be able to write it back
        fh.write("x")
    assert "cookiefile" not in YouTubeService(replace(settings, ytdlp_cookies_file=str(tmp_path / "nope"))).base_opts()
