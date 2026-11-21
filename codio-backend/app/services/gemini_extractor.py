"""
Codio Backend - Gemini VLM Code Extractor
Core VLM-based code extraction using Gemini API.
Robust JSON parsing to handle Gemini's varied output formats.
"""

import re
import json
import cv2
import base64
import logging
import numpy as np
from google import genai
from google.genai import types
from typing import Dict

from config.settings import get_gemini_api_key

logger = logging.getLogger(__name__)

GEMINI_API_KEY = get_gemini_api_key().strip()
MODEL_NAME = "gemini-3.5-flash-lite"


def _robust_json_parse(text: str) -> dict:
    """Parse JSON robustly, handling common Gemini output quirks."""
    # Strip markdown code fences
    cleaned = text.strip()
    if cleaned.startswith('```'):
        lines = cleaned.split('\n')
        # Remove first line (```json or ```) and last line (```)
        start = 1
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip().startswith('```'):
                end = i
                break
        cleaned = '\n'.join(lines[start:end]).strip()

    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Extract JSON object from text
    match = re.search(r'\{[\s\S]*\}', cleaned)
    if match:
        json_str = match.group(0)

        # Try direct parse of extracted JSON
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # Fix common issues:
        # 1. Replace JavaScript-style true/false/null
        fixed = json_str
        # 2. Remove trailing commas before } or ]
        fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
        # 3. Fix unquoted property names (simple cases)
        fixed = re.sub(r'(\{|,)\s*(\w+)\s*:', r'\1 "\2":', fixed)
        # 4. Replace single quotes with double quotes (careful with code_content)
        # Only do this if there are no double quotes at all
        if '"' not in fixed:
            fixed = fixed.replace("'", '"')

        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # Last resort: use ast.literal_eval for Python-style dicts
        try:
            import ast
            result = ast.literal_eval(json_str)
            if isinstance(result, dict):
                return result
        except (ValueError, SyntaxError):
            pass

    raise json.JSONDecodeError("Could not parse Gemini response as JSON", text, 0)


class GeminiCodeExtractor:
    """Core VLM-based code extraction using Gemini"""

    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

    def encode_frame(self, frame: np.ndarray) -> str:
        """Encode frame to base64 for Gemini API"""
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return base64.b64encode(buffer).decode('utf-8')

    def analyze_frame(self, frame: np.ndarray, timestamp: float) -> Dict:
        """Analyze a single frame using Gemini VLM"""
        if not GEMINI_API_KEY or GEMINI_API_KEY.lower() in {
            "placeholder",
            "your_gemini_api_key_here",
        }:
            return self._create_error_result(
                timestamp,
                "Gemini API key is not configured. Set PAUSE_TO_CODE_GEMINI_API_KEY or GEMINI_API_KEY in codio-backend/.env.",
                "gemini_api_key_missing",
            )

        try:
            prompt = """Analyze this coding tutorial video frame.

Your task:
1. Detect if the frame shows CODE (code editor, terminal, IDE) or LEARNING (slides, talking head, diagrams)
2. If code is visible, extract ALL the code exactly as shown, preserving indentation
3. If it's a learning frame, describe the topic briefly

You MUST respond with valid JSON in this exact format:
{
    "segment_type": "code",
    "has_code": true,
    "code_content": "the extracted code here",
    "learning_topic": null,
    "confidence": 0.95,
    "language": "python",
    "code_complete": true
}

Or for learning frames:
{
    "segment_type": "learning",
    "has_code": false,
    "code_content": null,
    "learning_topic": "topic being explained",
    "confidence": 0.95,
    "language": "python",
    "code_complete": false
}

Important rules:
- Return ONLY valid JSON, no markdown, no explanation
- Use double quotes for all strings
- Use true/false (lowercase) for booleans
- Use null (lowercase) for null values
- Extract code EXACTLY as shown on screen including comments
- confidence should be between 0.0 and 1.0
"""

            import PIL.Image
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = frame_rgb.shape[:2]
            max_side = max(h, w)
            if max_side > 1280:
                scale = 1280 / max_side
                new_w = max(1, int(w * scale))
                new_h = max(1, int(h * scale))
                frame_rgb = cv2.resize(frame_rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
            pil_image = PIL.Image.fromarray(frame_rgb)

            response = self.client.models.generate_content(
                model=MODEL_NAME,
                contents=[prompt, pil_image],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    top_p=0.9,
                    top_k=20,
                    max_output_tokens=1024,
                    response_mime_type="application/json",
                ),
            )

            response_text = (response.text or "").strip()
            logger.info(f"Gemini raw response at {timestamp:.2f}s: {response_text[:300]}")

            result = _robust_json_parse(response_text)
            result['timestamp'] = timestamp

            logger.info(f"Frame analysis at {timestamp:.2f}s: type={result.get('segment_type')}, has_code={result.get('has_code')}, confidence={result.get('confidence')}")
            return result

        except json.JSONDecodeError as e:
            logger.exception(f"JSON parse error at {timestamp:.2f}s: {e}")
            logger.error(f"Response text: {response_text[:500]}")
            return self._create_error_result(timestamp, f"JSON parse error: {e}")
        except Exception as e:
            logger.exception(f"Error analyzing frame at {timestamp:.2f}s")
            error_detail = str(e)
            if GEMINI_API_KEY:
                error_detail = error_detail.replace(GEMINI_API_KEY, "[redacted]")
            return self._create_error_result(timestamp, error_detail)

    def _create_error_result(
        self,
        timestamp: float,
        error_detail: str = "",
        error_code: str = "",
    ) -> Dict:
        """Create error result when analysis fails"""
        lowered = (error_detail or "").lower()
        error_code = error_code or "analysis_failed"
        if "429" in lowered or "quota" in lowered or "rate limit" in lowered:
            error_code = "gemini_quota_exceeded"

        return {
            "timestamp": timestamp,
            "segment_type": "learning",
            "has_code": False,
            "code_content": None,
            "learning_topic": "Analysis failed",
            "confidence": 0.0,
            "language": "python",
            "code_complete": False,
            "analysis_error_code": error_code,
            "analysis_error_detail": error_detail,
        }
