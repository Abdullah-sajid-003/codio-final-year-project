import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from flask import Flask

from app.routes.video import init_video_routes, video_bp
from app.services.pause_to_code import PauseToCodeService


class PauseToCodeErrorTests(unittest.TestCase):
    def test_analysis_error_details_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = object.__new__(PauseToCodeService)
            service.cache_dir = Path(temp_dir)
            service.realtime_analysis_cache = {}

            video_file = service.cache_dir / "videos" / "single" / "test-video" / "video.mp4"
            video_file.parent.mkdir(parents=True)
            video_file.touch()

            service.get_code_at_timestamp = lambda *_args, **_kwargs: {"found": False}
            service.processor = SimpleNamespace(
                extract_frame_at_timestamp=lambda *_args: np.zeros((2, 2, 3))
            )
            service.extractor = SimpleNamespace(
                analyze_frame=lambda *_args: {
                    "analysis_error_code": "gemini_api_key_missing",
                    "analysis_error_detail": "Gemini API key is not configured.",
                }
            )

            result = service.extract_frame_and_analyze("test-video", 1.0)

        self.assertEqual(result["error"], "gemini_api_key_missing")
        self.assertEqual(result["message"], "Gemini API key is not configured.")

    def test_frame_route_returns_failure_status_and_detail(self):
        service = SimpleNamespace(
            extract_frame_and_analyze=lambda *_args: {
                "error": "gemini_api_key_missing",
                "message": "Gemini API key is not configured.",
            }
        )
        init_video_routes(service)
        app = Flask(__name__)
        app.register_blueprint(video_bp)

        response = app.test_client().get(
            "/api/v1/video/test-video/frame?timestamp=1.0"
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["error"], "gemini_api_key_missing")
        self.assertEqual(
            response.get_json()["message"], "Gemini API key is not configured."
        )


if __name__ == "__main__":
    unittest.main()
