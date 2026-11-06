"""Instagram link validation and metadata handling (yt-dlp mocked)."""

import pytest

from instagram_service import InstagramService, classify_instagram_error, pick_video_entry
from utils.errors import PermanentError, TransientError
from utils.validators import canonical_instagram_url, extract_instagram_code, find_media

CODE = "C9abcDEF123"


@pytest.mark.parametrize("url", [
    f"https://www.instagram.com/reel/{CODE}/",
    f"https://instagram.com/reel/{CODE}/?igsh=MWQ1ZGUxMzBkMA==",
    f"https://www.instagram.com/p/{CODE}/",
    f"https://www.instagram.com/reels/{CODE}/",
    f"https://www.instagram.com/tv/{CODE}",
    f"https://m.instagram.com/p/{CODE}/",
    f"https://www.instagram.com/some.user/reel/{CODE}/",
    f"instagram.com/reel/{CODE}",
])
def test_valid_instagram_urls(url):
    assert extract_instagram_code(url) == CODE


@pytest.mark.parametrize("url", [
    "https://www.instagram.com/stories/user/123456789/",
    "https://www.instagram.com/some.user/",
    "https://instagram.com.evil.com/reel/C9abcDEF123/",
    "https://evil.com/reel/C9abcDEF123/",
    "https://www.instagram.com/reel/bad!code/",
    "http://127.0.0.1/reel/C9abcDEF123/",
])
def test_rejected_instagram_urls(url):
    assert extract_instagram_code(url) is None


def test_find_media_detects_platform():
    assert find_media("https://youtu.be/dQw4w9WgXcQ") == ("youtube", "dQw4w9WgXcQ")
    assert find_media(f"mana: https://www.instagram.com/reel/{CODE}/ zo'r") == ("instagram", CODE)
    assert find_media("salom") is None
    assert canonical_instagram_url(CODE) == f"https://www.instagram.com/p/{CODE}/"


def test_carousel_picks_first_video():
    info = {
        "_type": "playlist", "uploader": "user", "description": "Caption text",
        "entries": [
            {"id": "a", "vcodec": "none", "formats": [{"vcodec": "none"}]},
            {"id": "b", "formats": [{"vcodec": "h264"}]},
        ],
    }
    picked = pick_video_entry(info)
    assert picked["id"] == "b" and picked["uploader"] == "user"


def test_photo_only_post_rejected():
    with pytest.raises(PermanentError):
        pick_video_entry({"_type": "playlist", "entries": [{"id": "a", "vcodec": "none"}]})


def test_error_classification():
    assert isinstance(classify_instagram_error(Exception("login required to access this post")), PermanentError)
    assert isinstance(classify_instagram_error(Exception("This content is private")), PermanentError)
    assert type(classify_instagram_error(Exception("HTTP Error 429: Too Many Requests"))) is TransientError
    assert type(classify_instagram_error(Exception("Connection reset"))) is TransientError


def test_video_info_title_from_caption(settings):
    info = InstagramService.to_video_info(
        {"title": "Video by some_user", "description": "Ajoyib qo'shiq 🎵\n#music",
         "uploader": "some_user", "duration": 14.6, "thumbnail": "https://scontent.cdninstagram.com/x.jpg",
         "timestamp": 1762400000},
        CODE,
    )
    assert info.title == "Ajoyib qo'shiq 🎵"
    assert info.platform == "instagram" and info.duration == 14
    assert info.url == f"https://www.instagram.com/p/{CODE}/"


async def test_get_video_info_uses_canonical_url(settings, monkeypatch):
    service = InstagramService(settings)
    seen = {}

    def fake_extract(code):
        seen["code"] = code
        return {"title": "Reel", "uploader": "u", "formats": [{"vcodec": "h264"}], "duration": 10}

    monkeypatch.setattr(service, "extract_info_sync", fake_extract)
    info, raw = await service.get_video_info(CODE)
    assert seen["code"] == CODE and info.platform == "instagram"
    with pytest.raises(PermanentError):
        await service.get_video_info("../etc")
