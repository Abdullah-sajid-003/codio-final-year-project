import argparse
import json
import difflib
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


DEFAULT_VIDEO_URL = "https://www.youtube.com/watch?v=Gf9wLsCJDqc"
DEFAULT_TIMESTAMPS = [30, 60, 90, 120, 180, 240]


def compile_extracted_code(base_url: str, code: str) -> dict:
    try:
        response = requests.post(
            f"{base_url}/code/execute",
            json={"code": code},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        run = data.get("run", {})
        return {
            "success": data.get("success", False),
            "exit_code": run.get("code"),
            "stdout": run.get("stdout", ""),
            "stderr": run.get("stderr", ""),
            "source": data.get("source", "upstream"),
        }
    except requests.RequestException as error:
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": str(error),
            "source": "test_request_error",
        }


def normalize_code(code: str) -> str:
    return "\n".join(
        line.strip()
        for line in (code or "").replace("\r\n", "\n").splitlines()
        if line.strip()
    )


def text_similarity(extracted: str, expected: str) -> float:
    extracted_normalized = normalize_code(extracted)
    expected_normalized = normalize_code(expected)
    if not extracted_normalized and not expected_normalized:
        return 100.0
    if not extracted_normalized or not expected_normalized:
        return 0.0
    return round(difflib.SequenceMatcher(
        None,
        extracted_normalized,
        expected_normalized,
    ).ratio() * 100, 2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test video frame code extraction against the Codio compiler"
    )
    parser.add_argument("--video-url", default=DEFAULT_VIDEO_URL)
    parser.add_argument(
        "--timestamps",
        default="30,60,90,120,180,240",
        help="Comma-separated frame timestamps in seconds",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080/api/v1",
        help="Codio API base URL",
    )
    parser.add_argument(
        "--expected-code",
        default=None,
        help="Optional path to JSON mapping frame timestamps to expected code",
    )
    args = parser.parse_args()

    timestamps = [float(value.strip()) for value in args.timestamps.split(",") if value.strip()]
    output_dir = Path(__file__).resolve().parent / "test-results"
    output_dir.mkdir(exist_ok=True)

    print("CODIO VIDEO CODE EXTRACTION ACCURACY TEST")
    print("=" * 72)

    health = requests.get(args.base_url.replace("/api/v1", "/health"), timeout=10)
    health.raise_for_status()
    print(f"Backend health: {health.json().get('status')}")

    process = requests.post(
        f"{args.base_url}/video/process",
        json={"youtube_url": args.video_url, "full_process": False},
        timeout=90,
    )
    process.raise_for_status()
    process_data = process.json()
    if not process_data.get("success"):
        print(f"Video processing failed: {process_data}")
        return 1

    video_id = process_data["video_id"]
    print(f"Video ID: {video_id}")

    rows = []
    code_frames = 0
    compile_passes = 0
    runtime_passes = 0
    expected_samples = {}

    if args.expected_code:
        expected_path = Path(args.expected_code)
        if not expected_path.exists():
            print(f"Expected-code file not found: {expected_path}")
            return 1
        expected_samples = json.loads(expected_path.read_text(encoding="utf-8"))

    for timestamp in timestamps:
        print(f"\nTimestamp {timestamp:g}s:")
        response = requests.get(
            f"{args.base_url}/video/{video_id}/frame",
            params={"timestamp": timestamp},
            timeout=120,
        )

        if response.status_code != 200:
            row = {
                "timestamp": timestamp,
                "extraction": "failed",
                "error": response.json().get("message") or response.text,
                "confidence": 0.0,
                "code_complete": False,
                "compiler": "not_attempted",
            }
            print("  Extraction failed:", row["error"])
            rows.append(row)
            continue

        data = response.json()
        code = data.get("code_content")
        confidence = float(data.get("confidence", 0.0) or 0.0)
        code_complete = bool(data.get("code_complete", False))

        if not code or data.get("segment_type") != "code":
            row = {
                "timestamp": timestamp,
                "extraction": "no_code",
                "confidence": confidence,
                "code_complete": code_complete,
                "compiler": "not_attempted",
            }
            print("  No code frame detected")
            rows.append(row)
            continue

        code_frames += 1
        compiler = compile_extracted_code(args.base_url, code)
        compiled = compiler["success"] and compiler["exit_code"] == 0
        if compiled:
            compile_passes += 1
            runtime_passes += 1
        elif compiler["exit_code"] == 0:
            compile_passes += 1

        expected_code = expected_samples.get(str(timestamp)) or expected_samples.get(timestamp)
        similarity = (
            text_similarity(code, expected_code)
            if expected_code is not None
            else None
        )

        row = {
            "timestamp": timestamp,
            "extraction": "code",
            "confidence": confidence,
            "code_complete": code_complete,
            "language": data.get("language", "python"),
            "extracted_code": code,
            "compiler": "passed" if compiled else "failed",
            "compiler_exit_code": compiler["exit_code"],
            "compiler_stdout": compiler["stdout"],
            "compiler_stderr": compiler["stderr"],
            "compiler_source": compiler["source"],
            "exact_text_accuracy_percent": similarity,
        }
        print(f"  Code extracted (confidence={confidence:.2f}, complete={code_complete})")
        print(f"  Compiler: {'PASS' if compiled else 'FAIL'}")
        rows.append(row)

    compile_accuracy = (
        round((compile_passes / code_frames) * 100, 2) if code_frames else 0.0
    )
    runtime_accuracy = (
        round((runtime_passes / code_frames) * 100, 2) if code_frames else 0.0
    )
    extraction_accuracy = (
        round((code_frames / len(timestamps)) * 100, 2) if timestamps else 0.0
    )
    similarity_values = [
        row["exact_text_accuracy_percent"]
        for row in rows
        if row.get("exact_text_accuracy_percent") is not None
    ]
    exact_text_accuracy = (
        round(sum(similarity_values) / len(similarity_values), 2)
        if similarity_values
        else None
    )
    average_confidence = (
        round(
            sum(row["confidence"] for row in rows if row["extraction"] == "code")
            / code_frames,
            2,
        )
        if code_frames
        else 0.0
    )

    report = {
        "test_name": "Video Extracted Code Compiler Accuracy",
        "test_date": datetime.now(timezone.utc).isoformat(),
        "video_url": args.video_url,
        "video_id": video_id,
        "timestamps_tested": timestamps,
        "code_frames_detected": code_frames,
        "compiler_pass_count": compile_passes,
        "compiler_fail_count": code_frames - compile_passes,
        "frames_with_extracted_code_percent": extraction_accuracy,
        "compiler_accuracy_status": (
            f"{compile_accuracy:.2f}% ({compile_passes}/{code_frames} code frames)"
            if code_frames
            else "NOT MEASURABLE - no code frames extracted"
        ),
        "exact_text_accuracy_status": (
            f"{exact_text_accuracy:.2f}%"
            if exact_text_accuracy is not None
            else "NOT MEASURABLE - no expected-code dataset supplied"
        ),
        "compiler_pass_rate_percent": compile_accuracy,
        "runtime_pass_rate_percent": runtime_accuracy,
        "exact_text_accuracy_percent": exact_text_accuracy,
        "average_extraction_confidence": average_confidence,
        "rows": rows,
    }

    json_path = output_dir / "video-code-accuracy.json"
    text_path = output_dir / "video-code-accuracy.txt"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    text_lines = [
        "CODIO VIDEO CODE EXTRACTION ACCURACY TEST",
        "=" * 72,
        f"Test date: {report['test_date']}",
        f"Video: {args.video_url}",
        f"Video ID: {video_id}",
        f"Code frames detected: {code_frames}",
        f"Compiler pass count: {compile_passes}",
        f"Compiler fail count: {code_frames - compile_passes}",
        f"Extraction accuracy: {extraction_accuracy:.2f}% ({code_frames}/{len(timestamps)} timestamps)",
        (
            f"Compiler accuracy: {compile_accuracy:.2f}% ({compile_passes}/{code_frames} code frames)"
            if code_frames
            else "Compiler accuracy: NOT MEASURABLE - no code frames extracted"
        ),
        (
            f"Exact text accuracy: {exact_text_accuracy:.2f}%"
            if exact_text_accuracy is not None
            else "Exact text accuracy: NOT MEASURABLE - no expected-code dataset supplied"
        ),
        f"Runtime pass rate: {runtime_accuracy:.2f}% (if code frames were executable)",
        f"Average extraction confidence: {average_confidence:.2f}",
        "",
    ]
    for row in rows:
        text_lines.append(
            f"Timestamp {row['timestamp']:g}s | "
            f"extraction={row['extraction']} | "
            f"compiler={row['compiler']} | "
            f"confidence={row['confidence']:.2f}"
        )
    text_path.write_text("\n".join(text_lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"Code frames detected: {code_frames}")
    print(
        f"Extraction accuracy: {extraction_accuracy:.2f}% "
        f"({code_frames}/{len(timestamps)} timestamps)"
    )
    if code_frames:
        print(
            f"Compiler accuracy: {compile_accuracy:.2f}% "
            f"({compile_passes}/{code_frames} code frames)"
        )
    else:
        print("Compiler accuracy: NOT MEASURABLE - no code frames extracted")
    if exact_text_accuracy is not None:
        print(f"Exact-text accuracy: {exact_text_accuracy:.2f}%")
    else:
        print("Exact-text accuracy: NOT MEASURABLE - no expected-code dataset supplied")
    print(f"Average extraction confidence: {average_confidence:.2f}")
    print(f"Results: {json_path}")
    print(f"Text report: {text_path}")

    return 0 if code_frames > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
