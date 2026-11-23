import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


def run_check(name, operation):
    try:
        passed, detail = operation()
    except requests.RequestException as error:
        passed, detail = False, f"Request failed: {error}"
    return {
        "name": name,
        "passed": bool(passed),
        "detail": detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run API accuracy tests for authentication, quiz, and transcript features"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--admin-email", default="admin@gmail.com")
    parser.add_argument("--admin-password", default="")
    args = parser.parse_args()

    api = f"{args.base_url.rstrip('/')}/api/v1"
    results = []

    def valid_login():
        if not args.admin_password:
            return False, "No test password supplied"
        response = requests.post(
            f"{api}/auth/login",
            json={"email": args.admin_email, "password": args.admin_password},
            timeout=20,
        )
        data = response.json()
        return (
            response.status_code == 200
            and data.get("success") is True
            and bool(data.get("access_token")),
            f"HTTP {response.status_code}",
        )

    results.append(run_check("Authentication: valid admin login", valid_login))

    def invalid_login():
        response = requests.post(
            f"{api}/auth/login",
            json={"email": args.admin_email, "password": "Definitely-Wrong-Password"},
            timeout=20,
        )
        data = response.json()
        return (
            response.status_code in (401, 400)
            and data.get("success") is False,
            f"HTTP {response.status_code}",
        )

    results.append(run_check("Authentication: invalid password rejection", invalid_login))

    login_response = requests.post(
        f"{api}/auth/login",
        json={"email": args.admin_email, "password": args.admin_password},
        timeout=20,
    )
    login_data = login_response.json()
    if not login_data.get("access_token"):
        token = ""
    else:
        token = login_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    def quiz_session_start():
        if not token:
            return False, "Authentication token unavailable"
        response = requests.post(
            f"{api}/quiz/start",
            json={
                "user_email": args.admin_email,
                "transcript": (
                    "Python variables store values. x = 5 assigns the integer 5 to x. "
                    "A for loop repeats statements. A function is created using the def keyword."
                ),
                "video_id": "",
            },
            headers=headers,
            timeout=30,
        )
        data = response.json()
        passed = (
            response.status_code == 200
            and data.get("success") is True
            and bool(data.get("session_id"))
            and bool(data.get("first_question", {}).get("id"))
        )
        quiz_session_start.session_id = data.get("session_id")
        quiz_session_start.first_question = data.get("first_question")
        return passed, f"HTTP {response.status_code}; session={bool(data.get('session_id'))}"

    results.append(run_check("Quiz: session and question creation", quiz_session_start))

    def quiz_adaptive_wrong_answers():
        session_id = getattr(quiz_session_start, "session_id", None)
        current = getattr(quiz_session_start, "first_question", None)
        if not session_id or not current:
            return False, "Quiz session unavailable"

        levels = [1]
        for index in range(5):
            question_type = current.get("type")
            if question_type == "fill_in_blank":
                answer = "WRONG_FILL_BLANK"
            elif question_type == "true_false":
                answer = "definitely_wrong"
            else:
                answer = 999

            response = requests.post(
                f"{api}/quiz/submit-answer",
                json={
                    "session_id": session_id,
                    "question_id": current["id"],
                    "answer": answer,
                    "time_taken": 1,
                },
                headers=headers,
                timeout=30,
            )
            data = response.json()
            if response.status_code != 200 or data.get("success") is not True:
                return False, f"Question {index + 1} failed: HTTP {response.status_code}"
            levels.append(int(data.get("new_level", 1)))
            if data.get("next_question"):
                current = data["next_question"]
            elif not data.get("should_continue"):
                break

        ended = requests.post(
            f"{api}/quiz/end-session/{session_id}",
            headers=headers,
            timeout=30,
        )
        end_data = ended.json()
        passed = (
            ended.status_code == 200
            and end_data.get("success") is True
            and levels[-1] <= 2
        )
        return passed, f"difficulty levels={levels}; session ended={ended.status_code == 200}"

    results.append(run_check("Quiz: all-wrong answers reduce difficulty", quiz_adaptive_wrong_answers))

    def transcript_missing_query_validation():
        response = requests.get(
            f"{api}/video/Gf9wLsCJDqc/transcript/search",
            params={"query": ""},
            headers=headers,
            timeout=30,
        )
        data = response.json()
        return (
            response.status_code == 400
            and data.get("success") is False
            and "Missing" in data.get("error", ""),
            f"HTTP {response.status_code}",
        )

    results.append(
        run_check(
            "Transcript: missing search query validation",
            transcript_missing_query_validation,
        )
    )

    def transcript_no_match_contract():
        response = requests.get(
            f"{api}/video/Gf9wLsCJDqc/transcript/search",
            params={"query": "definitelynotpresentinthiscodiosample"},
            headers=headers,
            timeout=30,
        )
        data = response.json()
        return (
            response.status_code == 200
            and data.get("success") is True
            and data.get("matches_count") == 0
            and data.get("matches") == [],
            f"HTTP {response.status_code}; matches={data.get('matches_count')}",
        )

    results.append(
        run_check(
            "Transcript: non-existent term returns zero matches",
            transcript_no_match_contract,
        )
    )

    passed_count = sum(1 for result in results if result["passed"])
    total_count = len(results)
    accuracy = round((passed_count / total_count) * 100, 2) if total_count else 0.0

    feature_totals = {}
    for feature in ("Authentication", "Quiz", "Transcript"):
        feature_results = [
            result for result in results
            if result["name"].startswith(feature)
        ]
        feature_passed = sum(1 for result in feature_results if result["passed"])
        feature_totals[feature] = {
            "passed": feature_passed,
            "total": len(feature_results),
            "accuracy_percent": round(
                (feature_passed / len(feature_results)) * 100, 2
            ) if feature_results else 0.0,
        }

    report = {
        "test_name": "Codio Feature API Accuracy Test",
        "test_date": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "overall_accuracy_percent": accuracy,
        "passed": passed_count,
        "total": total_count,
        "feature_totals": feature_totals,
        "checks": results,
    }

    output_dir = Path(__file__).resolve().parent / "test-results"
    output_dir.mkdir(exist_ok=True)
    json_path = output_dir / "feature-api-accuracy.json"
    text_path = output_dir / "feature-api-accuracy.txt"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "CODIO FEATURE API ACCURACY TEST",
        "=" * 72,
        f"Test date: {report['test_date']}",
        f"Overall accuracy: {accuracy:.2f}% ({passed_count}/{total_count})",
        "",
    ]
    for feature, totals in feature_totals.items():
        lines.append(
            f"{feature} accuracy: {totals['accuracy_percent']:.2f}% "
            f"({totals['passed']}/{totals['total']})"
        )
    lines.append("")
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        lines.append(f"[{status}] {result['name']} - {result['detail']}")

    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    print(f"\nJSON report: {json_path}")
    print(f"Text report: {text_path}")
    return 0 if passed_count == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
