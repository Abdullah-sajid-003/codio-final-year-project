import unittest
from unittest.mock import patch

from app.services import youtube_data_api


class YouTubeDataAPITests(unittest.TestCase):
    def test_extract_video_id_from_supported_urls(self):
        self.assertEqual(
            youtube_data_api.extract_video_id("https://www.youtube.com/watch?v=abcdefghijk"),
            "abcdefghijk",
        )
        self.assertEqual(
            youtube_data_api.extract_video_id("https://youtu.be/abcdefghijk?t=10"),
            "abcdefghijk",
        )
        self.assertEqual(
            youtube_data_api.extract_video_id("https://youtube.com/shorts/abcdefghijk"),
            "abcdefghijk",
        )

    def test_duration_seconds_parses_youtube_iso_duration(self):
        self.assertEqual(youtube_data_api._duration_seconds("PT1H2M3S"), 3723)
        self.assertEqual(youtube_data_api._duration_seconds("PT90S"), 90)
        self.assertEqual(youtube_data_api._duration_seconds("invalid"), 0)

    def test_playlist_response_uses_api_metadata_and_video_details(self):
        def fake_api_get(resource, params):
            if resource == "playlists":
                return {"items": [{"snippet": {"title": "Python Basics"}}]}
            if resource == "playlistItems":
                return {
                    "items": [
                        {
                            "contentDetails": {"videoId": "abcdefghijk"},
                            "snippet": {"resourceId": {"videoId": "abcdefghijk"}},
                        }
                    ]
                }
            if resource == "videos":
                return {
                    "items": [
                        {
                            "id": "abcdefghijk",
                            "snippet": {
                                "title": "Variables",
                                "channelTitle": "Codio",
                                "thumbnails": {"medium": {"url": "https://example.test/thumb.jpg"}},
                            },
                            "contentDetails": {"duration": "PT2M30S"},
                            "statistics": {"viewCount": "1200"},
                        }
                    ]
                }
            self.fail(f"Unexpected API resource: {resource}")

        with patch.object(youtube_data_api, "_api_get", side_effect=fake_api_get):
            result = youtube_data_api.get_playlist_videos(
                "https://www.youtube.com/playlist?list=PL123"
            )

        self.assertEqual(result["playlist_title"], "Python Basics")
        self.assertEqual(len(result["videos"]), 1)
        self.assertEqual(result["videos"][0]["video_id"], "abcdefghijk")
        self.assertEqual(result["videos"][0]["duration"], 150)
        self.assertEqual(result["videos"][0]["title"], "Variables")

    def test_search_response_matches_frontend_video_shape(self):
        def fake_api_get(resource, params):
            if resource == "search":
                return {
                    "items": [
                        {
                            "id": {"videoId": "abcdefghijk"},
                            "snippet": {"title": "Variables"},
                        }
                    ]
                }
            if resource == "videos":
                return {
                    "items": [
                        {
                            "id": "abcdefghijk",
                            "snippet": {
                                "title": "Variables",
                                "channelTitle": "Codio",
                                "channelId": "UC123",
                                "publishedAt": "2024-01-01T00:00:00Z",
                                "description": "A Python lesson.",
                            },
                            "contentDetails": {"duration": "PT90S"},
                            "statistics": {"viewCount": "1200"},
                        }
                    ]
                }
            self.fail(f"Unexpected API resource: {resource}")

        with patch.object(youtube_data_api, "_api_get", side_effect=fake_api_get):
            videos = youtube_data_api.search_videos("python", 10)

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["video_id"], "abcdefghijk")
        self.assertEqual(videos[0]["channel"], "Codio")
        self.assertEqual(videos[0]["duration"], 90)
        self.assertEqual(videos[0]["views"], 1200)
        self.assertEqual(videos[0]["views_text"], "1.2K views")

    def test_api_key_is_required(self):
        with patch.object(youtube_data_api, "YOUTUBE_API_KEY", ""):
            with self.assertRaisesRegex(
                youtube_data_api.YouTubeDataAPIError,
                "YOUTUBE_API_KEY is not configured",
            ):
                youtube_data_api._api_get("videos", {"part": "snippet"})


if __name__ == "__main__":
    unittest.main()
