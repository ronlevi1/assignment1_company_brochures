"""Run the existing Phase 2 selection from saved inputs in a local terminal."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from urllib.parse import urljoin

import httpx
from openai import APIError, APIStatusError

from config import GEMINI_BASE_URL, MODEL, create_client
from utils import validate_selection


def select_once(client, folder):
    input_path = folder / "input.json"
    inputs = json.loads(input_path.read_text(encoding="utf-8"))
    result_path = folder / "result.json"
    attempt = {
        "run_id": folder.parent.name, "action": "link_selection", "company": inputs["company"],
        "audience": ["potential customers", "job candidates"], "model": inputs["model"],
        "started_at": datetime.now(timezone.utc).isoformat(), "input_path": input_path.as_posix(),
        "output_path": result_path.as_posix(),
    }
    try:
        with (folder / "attempt.json").open("x", encoding="utf-8") as log:
            json.dump(attempt, log, indent=2)
    except FileExistsError:
        return

    result = {**attempt, "outcome": "call_failed", "validation": "not_run"}
    started = perf_counter()
    http_response = None
    try:
        raw = client.chat.completions.with_raw_response.create(
            model=inputs["model"], messages=inputs["messages"], response_format=inputs["response_format"]
        )
        http_response = raw.http_response
    except APIError as exc:
        # Log exception types only. Transport error strings can contain credentials.
        result["error_type"] = type(exc).__name__
        if exc.__cause__:
            result["cause_type"] = type(exc.__cause__).__name__
        if isinstance(exc, APIStatusError):
            http_response = exc.response
    result["duration_seconds"] = round(perf_counter() - started, 3)

    if http_response is not None:
        result["http_status"] = http_response.status_code
        response_path = folder / "response.json"
        response_path.write_bytes(http_response.content)
        result["raw_response_path"] = response_path.as_posix()
        if http_response.is_success:
            try:
                envelope = http_response.json()
                if not isinstance(envelope, dict):
                    raise ValueError("Expected a completion response object.")
                if isinstance(envelope.get("usage"), dict):
                    result["usage"] = envelope["usage"]
                answer = envelope["choices"][0]["message"]["content"]
                links = validate_selection(answer, inputs["homepage"], inputs["candidates"])
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                result.update(outcome="rejected", validation="rejected", reason=str(exc))
            else:
                result.update(outcome="accepted", validation="valid", links=links)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_connectivity():
    """Read Google's public API discovery document using the normal HTTPS route."""
    url = urljoin(GEMINI_BASE_URL, "/$discovery/rest?version=v1beta")
    try:
        response = httpx.get(url, timeout=8)
        response.raise_for_status()
        document = response.json()
        if isinstance(document, dict) and document.get("name") == "generativelanguage":
            print("Connectivity OK: Google returned its public Gemini API description.")
            return True
        print("Connectivity unconfirmed: unexpected discovery response.")
    except httpx.HTTPStatusError as exc:
        print(f"Connectivity unconfirmed: discovery returned HTTP {exc.response.status_code}.")
    except (httpx.RequestError, ValueError) as exc:
        print(f"Connectivity unconfirmed: {type(exc).__name__}.")
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Allow the second recorded attempt.")
    parser.add_argument("--company", choices=("A", "B"), help="Select one company only.")
    args = parser.parse_args()
    if not args.execute:
        return 0 if check_connectivity() else 1

    saved = Path("runs/phase2-for-20261124T144231622541Z")
    company_ids = [args.company] if args.company else ["A", "B"]
    attempt_number = 2
    if args.company:
        while (saved.with_name(saved.name + f"-attempt-{attempt_number:02d}") / args.company).exists():
            attempt_number += 1
    retry = saved.with_name(saved.name + f"-attempt-{attempt_number:02d}")
    folders = [retry / company_id for company_id in company_ids]
    inputs = {}
    for company_id in company_ids:
        data = (saved / company_id / "input.json").read_bytes()
        if json.loads(data)["model"] != MODEL:
            raise SystemExit("Configured model differs from the saved selection input.")
        inputs[company_id] = data
    if not check_connectivity():
        print("Stopped before model selection.")
        return 1
    with create_client() as client:
        for folder in folders:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "input.json").write_bytes(inputs[folder.name])
            select_once(client, folder)

    valid_count = 0
    for folder in folders:
        path = folder / "result.json"
        if path.exists():
            result = json.loads(path.read_text(encoding="utf-8"))
            print(f"{result['company']}: {result['outcome']} | JSON {result['validation']} | {path}")
            valid_count += result["validation"] == "valid"
        else:
            print(f"{folder.name}: attempt recorded without a saved result.")
    return 0 if valid_count == len(folders) else 1


if __name__ == "__main__":
    raise SystemExit(main())
