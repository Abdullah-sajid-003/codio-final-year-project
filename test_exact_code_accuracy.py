import difflib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BACKEND_DIR = Path(__file__).resolve().parent / "codio-backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.gemini_extractor import GeminiCodeExtractor
from app.services.code_execution import execute_python_code_locally


GROUND_TRUTH = [
    {
        "name": "variables",
        "code": 'x = str(3)\ny = int(3)\nz = float(3)\nprint(x, y, z)',
        "output": "3 3 3.0",
    },
    {
        "name": "for_loop",
        "code": 'total = 0\nfor number in range(1, 5):\n    total += number\nprint(total)',
        "output": "10",
    },
    {
        "name": "function",
        "code": 'def add(a, b):\n    return a + b\n\nprint(add(4, 7))',
        "output": "11",
    },
]


def normalize_code(code: str) -> str:
    lines = [
        line.rstrip()
        for line in (code or "").replace("\r\n", "\n").splitlines()
    ]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def exact_accuracy(extracted: str, expected: str) -> float:
    extracted = normalize_code(extracted)
    expected = normalize_code(expected)
    if extracted == expected:
        return 100.0
    if not extracted or not expected:
        return 0.0
    return 0.0


def similarity_accuracy(extracted: str, expected: str) -> float:
    extracted = normalize_code(extracted)
    expected = normalize_code(expected)
    if not extracted or not expected:
        return 0.0
    return round(
        difflib.SequenceMatcher(None, extracted, expected).ratio() * 100,
        2,
    )


def render_code_frame(code: str) -> np.ndarray:
    width, height = 1280, 720
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype("consola.ttf", 38)
        header_font = ImageFont.truetype("consola.ttf", 32)
    except OSError:
        font = ImageFont.load_default()
        header_font = ImageFont.load_default()

    draw.rectangle((0, 0, width, 70), fill="#20242a")
    draw.text((30, 18), "Python Editor", fill="white", font=header_font)
    draw.rectangle((0, 70, width, height), fill="#fafafa")

    y = 115
    for line_number, line in enumerate(code.splitlines(), start=1):
        draw.text((30, y), f"{line_number:2}", fill="#888888", font=font)
        draw.text((95, y), line, fill="#111111", font=font)
        y += 55

    frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    return frame


def analyze_with_retries(extractor, frame, timestamp, retries=3):
    for attempt in range(retries):
        result = extractor.analyze_frame(frame, timestamp)
        if not result.get("analysis_error_code"):
            return result
        time.sleep(2 * (attempt + 1))
    return result


def main() -> int:
    print("CODIO EXACT CODE EXTRACTION ACCURACY TEST")
    print("=" * 72)
    extractor = GeminiCodeExtractor()

    if extractor.client is None:
        print("FAIL: Gemini API key is not configured.")
        return 1

    rows = []
    exact_matches = 0
    compiler_passes = 0
    output_matches = 0
    similarity_total = 0.0

    for index, sample in enumerate(GROUND_TRUTH, start=1):
        print(f"\n[{index}] {sample['name']}")
        frame = render_code_frame(sample["code"])
        result = analyze_with_retries(extractor, frame, float(index))
        extracted = result.get("code_content") or ""

        exact = exact_accuracy(extracted, sample["code"])
        similarity = similarity_accuracy(extracted, sample["code"])
        if exact == 100.0:
            exact_matches += 1
        similarity_total += similarity

        compiler = execute_python_code_locally(extracted)
        compiled = compiler["code"] == 0
        if compiled:
            compiler_passes += 1

        actual_output = (compiler["stdout"] or "").strip()
        expected_output = sample["output"]
        output_matched = compiled and actual_output == expected_output
        if output_matched:
            output_matches += 1

        row = {
            "name": sample["name"],
            "ground_truth_code": sample["code"],
            "extracted_code": extracted,
            "exact_match_percent": exact,
            "similarity_percent": similarity,
            "compiler_passed": compiled,
            "compiler_exit_code": compiler["code"],
            "expected_output": expected_output,
            "actual_output": actual_output,
            "output_match": output_matched,
            "extraction_confidence": float(result.get("confidence", 0.0) or 0.0),
            "extraction_error": result.get("analysis_error_detail"),
        }
        rows.append(row)

        print(f"  Exact match: {exact:.2f}%")
        print(f"  Text similarity: {similarity:.2f}%")
        print(f"  Compiler: {'PASS' if compiled else 'FAIL'}")
        print(f"  Output match: {'PASS' if output_matched else 'FAIL'}")

    total = len(GROUND_TRUTH)
    report = {
        "test_name": "Controlled Exact Code Extraction Accuracy",
        "test_date": datetime.now(timezone.utc).isoformat(),
        "test_type": "Known code rendered on synthetic IDE frames",
        "ground_truth_samples": total,
        "exact_match_count": exact_matches,
        "exact_match_accuracy_percent": round(exact_matches / total * 100, 2),
        "average_text_similarity_percent": round(similarity_total / total, 2),
        "compiler_pass_count": compiler_passes,
        "compiler_accuracy_percent": round(compiler_passes / total * 100, 2),
        "output_match_count": output_matches,
        "output_accuracy_percent": round(output_matches / total * 100, 2),
        "rows": rows,
    }

    output_dir = Path(__file__).resolve().parent / "test-results"
    output_dir.mkdir(exist_ok=True)
    json_path = output_dir / "exact-code-accuracy.json"
    text_path = output_dir / "exact-code-accuracy.txt"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    text_lines = [
        "CODIO EXACT CODE EXTRACTION ACCURACY TEST",
        "=" * 72,
        f"Test date: {report['test_date']}",
        "Ground truth: known code rendered onto controlled IDE frames",
        f"Ground-truth samples: {total}",
        f"Exact match accuracy: {report['exact_match_accuracy_percent']:.2f}% "
        f"({exact_matches}/{total})",
        f"Average text similarity: {report['average_text_similarity_percent']:.2f}%",
        f"Compiler accuracy: {report['compiler_accuracy_percent']:.2f}% "
        f"({compiler_passes}/{total})",
        f"Expected-output accuracy: {report['output_accuracy_percent']:.2f}% "
        f"({output_matches}/{total})",
        "",
    ]
    for row in rows:
        text_lines.append(
            f"{row['name']} | exact={row['exact_match_percent']:.2f}% | "
            f"similarity={row['similarity_percent']:.2f}% | "
            f"compiler={'PASS' if row['compiler_passed'] else 'FAIL'} | "
            f"output={'PASS' if row['output_match'] else 'FAIL'}"
        )
    text_path.write_text("\n".join(text_lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 72)
    print(
        f"Exact match accuracy: {report['exact_match_accuracy_percent']:.2f}% "
        f"({exact_matches}/{total})"
    )
    print(
        f"Average text similarity: {report['average_text_similarity_percent']:.2f}%"
    )
    print(
        f"Compiler accuracy: {report['compiler_accuracy_percent']:.2f}% "
        f"({compiler_passes}/{total})"
    )
    print(
        f"Expected-output accuracy: {report['output_accuracy_percent']:.2f}% "
        f"({output_matches}/{total})"
    )
    print(f"JSON report: {json_path}")
    print(f"Text report: {text_path}")
    return 0 if exact_matches == total else 1


if __name__ == "__main__":
    sys.exit(main())
