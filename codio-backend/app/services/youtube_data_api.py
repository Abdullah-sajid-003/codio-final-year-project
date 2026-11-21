"""Small client for the official YouTube Data API v3."""

import re
from datetime import datetime, timezone
from typing import Dict, List
from urllib.parse import parse_qs, urlparse

import requests

from config.settings import YOUTUBE_API_KEY


_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
_DURATION_PATTERN = re.compile(
    r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$"
)


class YouTubeDataAPIError(RuntimeError):
    """Raised when a YouTube Data API request cannot be completed."""


def extract_video_id(youtube_url: str) -> str:
    """Extract a YouTube video ID from a supported URL or raw ID."""
    value = youtube_url.strip()
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()

    if hostname == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    elif hostname == "youtube.com" or hostname.endswith(".youtube.com"):
        query_id = parse_qs(parsed.query).get("v", [])
        if query_id:
            video_id = query_id[0]
        else:
            segments = [segment for segment in parsed.path.split("/") if segment]
            video_id = segments[1] if len(segments) > 1 and segments[0] in {
                "embed",
                "live",
                "shorts",
            } else ""
    else:
        video_id = value

    if not _VIDEO_ID_PATTERN.fullmatch(video_id):
        raise ValueError("A valid YouTube video URL or video ID is required.")
    return video_id


def _extract_playlist_id(youtube_url: str) -> str:
    return parse_qs(urlparse(youtube_url).query).get("list", [""])[0]


def _api_get(resource: str, params: Dict) -> Dict:
    api_key = YOUTUBE_API_KEY
    if not api_key:
        raise YouTubeDataAPIError("YOUTUBE_API_KEY is not configured on the backend.")

    try:
        response = requests.get(
            f"{_API_BASE_URL}/{resource}",
            params={**params, "key": api_key},
            timeout=15,
        )
    except requests.RequestException:
        raise YouTubeDataAPIError("Could not connect to the YouTube Data API.") from None

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not response.ok:
        message = payload.get("error", {}).get("message")
        raise YouTubeDataAPIError(message or "YouTube Data API request failed.")
    return payload


def _duration_seconds(duration: str) -> int:
    match = _DURATION_PATTERN.fullmatch(duration or "")
    if not match:
        return 0
    days, hours, minutes, seconds = match.groups()
    return int(
        (int(days or 0) * 86400)
        + (int(hours or 0) * 3600)
        + (int(minutes or 0) * 60)
        + float(seconds or 0)
    )


def _thumbnail(snippet: Dict, video_id: str) -> str:
    thumbnails = snippet.get("thumbnails", {})
    for size in ("maxres", "high", "medium", "default"):
        item = thumbnails.get(size)
        if item and item.get("url"):
            return item["url"]
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _video_details_by_ids(video_ids: List[str]) -> Dict[str, Dict]:
    if not video_ids:
        return {}
    payload = _api_get(
        "videos",
        {
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(video_ids),
        },
    )
    return {item["id"]: item for item in payload.get("items", [])}


def _format_video(item: Dict) -> Dict:
    video_id = item["id"]
    snippet = item.get("snippet", {})
    details = item.get("contentDetails", {})
    statistics = item.get("statistics", {})
    return {
        "video_id": video_id,
        "title": snippet.get("title", "Untitled"),
        "thumbnail": _thumbnail(snippet, video_id),
        "duration": _duration_seconds(details.get("duration", "")),
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "author": snippet.get("channelTitle", "Unknown"),
        "views": int(statistics.get("viewCount", 0) or 0),
    }


def get_video_details(youtube_url_or_id: str) -> Dict:
    """Return normalized details for a publicly accessible video."""
    video_id = extract_video_id(youtube_url_or_id)
    items = _api_get(
        "videos",
        {"part": "snippet,contentDetails,statistics", "id": video_id},
    ).get("items", [])
    if not items:
        raise YouTubeDataAPIError("Video was not found or is not accessible through the API.")
    return _format_video(items[0])


def get_playlist_videos(youtube_url: str) -> Dict:
    """Return normalized videos for a public playlist or a single video URL."""
    playlist_id = _extract_playlist_id(youtube_url)
    if not playlist_id:
        video = get_video_details(youtube_url)
        return {"playlist_title": video["title"], "videos": [video]}

    playlist_items = _api_get(
        "playlists",
        {"part": "snippet", "id": playlist_id},
    ).get("items", [])
    if not playlist_items:
        raise YouTubeDataAPIError("Playlist was not found or is not publicly accessible.")

    playlist_title = playlist_items[0].get("snippet", {}).get("title", "YouTube Playlist")
    video_ids: List[str] = []
    page_token = None

    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token

        page = _api_get("playlistItems", params)
        for item in page.get("items", []):
            video_id = (
                item.get("contentDetails", {}).get("videoId")
                or item.get("snippet", {}).get("resourceId", {}).get("videoId")
            )
            if video_id:
                video_ids.append(video_id)

        page_token = page.get("nextPageToken")
        if not page_token:
            break

    videos_by_id: Dict[str, Dict] = {}
    for start in range(0, len(video_ids), 50):
        videos_by_id.update(_video_details_by_ids(video_ids[start : start + 50]))

    videos = [
        _format_video(videos_by_id[video_id])
        for video_id in video_ids
        if video_id in videos_by_id
    ]
    if not videos:
        raise YouTubeDataAPIError("No publicly accessible videos were found in this playlist.")

    return {"playlist_title": playlist_title, "videos": videos}


def _relative_published_date(published_at: str) -> str:
    if not published_at:
        return ""
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - published).days
    except ValueError:
        return published_at

    if days < 1:
        return "today"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        return f"{days // 7} weeks ago"
    if days < 365:
        return f"{days // 30} months ago"
    return f"{days // 365} years ago"


def _views_text(views: int) -> str:
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M views"
    if views >= 1_000:
        return f"{views / 1_000:.1f}K views"
    return f"{views} views"


def search_videos(query: str, max_results: int = 20) -> List[Dict]:
    """Search publicly available videos and return the frontend response shape."""
    max_results = max(1, min(int(max_results), 50))
    search_items = _api_get(
        "search",
        {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
        },
    ).get("items", [])

    video_ids = [
        item.get("id", {}).get("videoId")
        for item in search_items
        if item.get("id", {}).get("videoId")
    ]
    details_by_id = _video_details_by_ids(video_ids)
    videos = []

    for item in search_items:
        video_id = item.get("id", {}).get("videoId")
        details = details_by_id.get(video_id)
        if not video_id or not details:
            continue

        video = _format_video(details)
        snippet = details.get("snippet", item.get("snippet", {}))
        views = video["views"]
        videos.append(
            {
                **video,
                "channel": snippet.get("channelTitle", "Unknown"),
                "channel_id": snippet.get("channelId", ""),
                "views_text": _views_text(views),
                "published": _relative_published_date(snippet.get("publishedAt", "")),
                "description": (snippet.get("description", "") or "")[:200],
            }
        )

    return videos
