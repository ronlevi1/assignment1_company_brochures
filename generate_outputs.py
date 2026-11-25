"""Phase 4: generate from the frozen Phase 3 contexts in a local terminal."""

import argparse
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from openai import APIStatusError

from collect_sources import read_json, save_json
from config import COMPANIES, COMPARISON_DIMENSIONS, MODEL, create_client
from prompts import build_brochure_messages, build_comparison_messages
from utils import validate_output


SOURCE_DIR = Path("runs/phase3-20261124T220906347169Z")
OUTPUTS = ("A-customer", "A-candidate", "B-customer", "B-candidate", "comparison", "A-customer-baseline")
EVALUATION = {
    "criteria": ["Factual faithfulness", "Audience suitability", "Information coverage", "Clarity"],
    "audit_rule": "In reading order, take the first two substantial, verifiable factual claims "
                 "from each main brochure, regardless of citation or apparent correctness. "
                 "Exclude the baseline and source lists. Record a shortfall if fewer than two qualify.",
}


def prepare(name):
    comparison = name == "comparison"
    company, audience = ("A+B", "customers and candidates") if comparison else name.split("-")[:2]
    path = SOURCE_DIR / f"context_{'comparison' if comparison else company}.json"
    record = read_json(path)
    context = record["context"]
    sources = {}
    for row in record["allocations"]:
        if row["used_chars"]:
            sid = row["source_id"]
            source = read_json(SOURCE_DIR / f"{sid}.json")
            if f"[{sid}] {source['title']}\n{source['url']}\n" not in context:
                raise ValueError(f"Missing source header for {sid} in {path}")
            sources[sid] = source["url"]
    if comparison:
        messages = build_comparison_messages([c["name"] for c in COMPANIES.values()], COMPARISON_DIMENSIONS, context)
    else:
        messages = build_brochure_messages(COMPANIES[company]["name"], audience, context, name.endswith("-baseline"))
    return dict(action=name, company=company, audience=audience, context_path=path.as_posix(),
                sources=sources, model=MODEL, messages=messages, stream=name == "B-candidate")


def consume_stream(events, event_log, parts, state):
    """Record each available SDK event, including events carrying only usage."""
    for event in events:
        event_log.write(event.model_dump_json(exclude_unset=True) + "\n")
        event_log.flush()
        if getattr(event, "usage", None) is not None:
            state["usage"] = event.usage.model_dump(exclude_unset=True)
        if not event.choices:
            continue
        choice = event.choices[0]
        if choice.finish_reason:
            state["finish_reason"] = choice.finish_reason
        chunk = getattr(choice.delta, "content", None)
        if chunk:
            parts.append(chunk)
            print(chunk, end="", flush=True)


def generate(client, inputs, folder):
    """Display and return the text, saving partial text even on stream failure."""
    folder.mkdir()
    input_path = folder / "input.json"
    output_path = folder / "output.md"
    save_json(input_path, inputs)  # The user message contains the exact saved context.
    stream = inputs["stream"]
    state = dict(run_id=folder.parent.name, action=inputs["action"], company=inputs["company"],
                 audience=inputs["audience"], model=inputs["model"], started_at=datetime.now(timezone.utc).isoformat(),
                 input_path=input_path.as_posix(), output_path=output_path.as_posix(), status="started")
    result_path = folder / "result.json"
    save_json(result_path, state)
    parts = []
    started = perf_counter()
    stream_opened = False
    try:
        params = {key: inputs[key] for key in ("model", "messages", "stream")}
        completions = client.chat.completions
        if stream:
            with closing(completions.create(**params)) as events:
                stream_opened = True
                with (folder / "events.jsonl").open("x", encoding="utf-8") as log:
                    consume_stream(events, log, parts, state)
        else:
            raw = completions.with_raw_response.create(**params)
            (folder / "response.json").write_bytes(raw.http_response.content)
            envelope = raw.http_response.json()
            if isinstance(envelope.get("usage"), dict):
                state["usage"] = envelope["usage"]
            choice = envelope["choices"][0]
            state["finish_reason"] = choice.get("finish_reason")
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Missing message content")
            parts.append(content)
            print(content)
        state["status"] = "complete" if state.get("finish_reason") == "stop" else "partial"
    except (Exception, KeyboardInterrupt) as exc:
        state.update(status="partial" if stream_opened else "failed", error=type(exc).__name__)
        if isinstance(exc, APIStatusError):
            state["http_status"] = exc.status_code
            (folder / "response.json").write_bytes(exc.response.content)
        if isinstance(exc, KeyboardInterrupt):
            raise
    finally:
        state["duration_seconds"] = round(perf_counter() - started, 3)
        text = "".join(parts)
        output_path.write_bytes(text.encode("utf-8"))
        state["validation"] = validate_output(text, inputs["sources"], inputs["action"] != "comparison")
        if state["status"] == "complete" and not state["validation"]["valid"]:
            state["status"] = "invalid"
        save_json(result_path, state)
        print(f"\n{inputs['action']}: {state['status']} ({folder})")
    return text


def saved_results():
    """Prefer completed outputs; otherwise show the latest recorded attempt."""
    results = {}
    for path in sorted(Path("runs").glob("phase4-*/*/result.json")):
        state = read_json(path)
        if state["status"] == "invalid" and "Source list differs from the cited IDs and URLs" in state["validation"]["errors"]:
            # Read old brochures under the current rules without changing their historical logs.
            inputs = read_json(path.with_name("input.json"))
            text = path.with_name("output.md").read_bytes().decode("utf-8")
            state["validation"] = validate_output(text, inputs["sources"])
            if state["validation"]["valid"]:
                state["status"] = "complete"
        name = state["action"]
        if state["status"] == "complete" or name not in results or results[name]["status"] != "complete":
            results[name] = state
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", choices=OUTPUTS, help="Run one missing output or explicitly retry a failed attempt.")
    parser.add_argument("--force", action="store_true", help="Generate a fresh attempt for the selected output.")
    args = parser.parse_args()
    if args.force and not args.output:
        parser.error("--force requires --output")
    saved = saved_results()
    names = [args.output] if args.output else OUTPUTS
    pending = []
    for name in names:
        if args.force or name not in saved or (args.output and saved[name]["status"] != "complete"):
            inputs = prepare(name)
            partner = {"A-customer": "A-customer-baseline", "A-customer-baseline": "A-customer"}.get(name)
            if partner in saved and saved[partner]["status"] == "complete":
                prior = read_json(Path(saved[partner]["input_path"]))
                if (inputs["model"], inputs["stream"], inputs["messages"][1]) != (
                    prior["model"], prior["stream"], prior["messages"][1]
                ):
                    raise ValueError("The model, settings or context differ from the saved experiment partner.")
            pending.append(inputs)
        else:
            print(name, "already recorded:", saved[name]["status"])
    print("Planned calls:", len(pending))
    if not args.execute or not pending:
        return
    folder = Path("runs") / datetime.now(timezone.utc).strftime("phase4-%Y%m%dT%H%M%S%fZ")
    folder.mkdir()
    save_json(folder / "evaluation.json", EVALUATION)
    with create_client() as client:
        for inputs in pending:
            generate(client, inputs, folder / inputs["action"])


if __name__ == "__main__":
    main()
