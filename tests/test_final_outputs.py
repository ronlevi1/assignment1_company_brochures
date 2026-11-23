"""Offline writing recovery, citation scope and SDK stream termination."""
import json
from types import SimpleNamespace as N
from unittest.mock import Mock

import httpx
import pytest
from openai import OpenAI, Stream
from openai.types.chat import ChatCompletionChunk

from config import Company, Settings
from context_manager import build_context
from llm_service import _read_stream
from prompt_builder import DIMENSIONS, MISSING, SYSTEM, comparison_prompt
from scraper import Page
from storage import Run, dump_json, dump_text, read_json
from validators import validate_comparison
from workflow import export, replay, resume_workflow, run_events, run_workflow, writing_checkpoint
from test_outputs import brochure, event, source, table


@pytest.mark.parametrize(("finish", "done", "expected"), [
    ("stop", True, None), ("STOP", True, None), ("length", True, "length"),
    (None, True, "missing finish event"), (None, False, "missing finish event"),
])
def test_sdk_gemini_stream(finish, done, expected):
    def frame(choices, **extra):
        data = dict(id="fixture", object="chat.completion.chunk", model="gemini-3.5-flash-lite",
                    created=1, choices=choices, **extra)
        return "data: " + json.dumps(data) + "\n\n"
    frames = [frame([dict(index=0, delta={"role": "assistant"}, finish_reason=None)]),
              frame([dict(index=0, delta={"content": "ראיה\r\n"}, finish_reason=None)])]
    if finish:
        frames.append(frame([dict(index=0, delta={}, finish_reason=finish)]))
    frames.append(frame([], usage=dict(prompt_tokens=4, completion_tokens=2, total_tokens=6)))
    if done:
        frames.append("data: [DONE]\n\n")
    with OpenAI(api_key="fixture", max_retries=0) as client:
        stream = Stream(cast_to=ChatCompletionChunk, client=client,
                        response=httpx.Response(200, content="".join(frames).encode()))
        diagnostics, displays = {}, []
        text, error, usage = _read_stream(stream, displays.append, diagnostics)
    assert text == "ראיה\r\n" and displays == [text] and usage["total_tokens"] == 6
    assert diagnostics["iterator_end"] == "exhausted" and diagnostics["finish_reason"] == finish
    assert error == ("incomplete stream: " + expected if expected else None)


@pytest.mark.parametrize(("citation", "valid"), [
    ("[A1, B1]", True), ("[A1] [B1]", True), ("[A1, B2]", False),
    ("[A1, Z9]", False), ("[A1,, B1]", False), ("[A1, B1", False), ("[A1]", False),
])
def test_comparison_checks_each_group_member_and_both_companies(citation, valid):
    sources = [source("A1", "x"), source("B1", "y"), source("B2", "z")]
    ctx = build_context(sources[:2], 100)
    text = table().replace(MISSING, "הבדל " + citation)
    if valid:
        assert validate_comparison(text, ctx, sources, DIMENSIONS)["dimensions"] == DIMENSIONS
        with pytest.raises(ValueError):
            validate_comparison(text.replace("מידע [A1]", "מידע [A1, B1]"), ctx, sources, DIMENSIONS)
    else:
        with pytest.raises(ValueError):
            validate_comparison(text, ctx, sources, DIMENSIONS)


def test_legacy_comparison_revalidated_without_rewriting_or_resampling(tmp_path):
    run = Run.new(tmp_path)
    companies = tuple(Company(c,c,f"https://{c.lower()}.test/") for c in "AB")
    collections = {c.id:[source(c.id+"1", "data")] for c in companies}
    ctx = build_context(collections["A"]+collections["B"], 100)
    args = (run.root, {"format_version":2, "model":"fixture", "budget":100}, companies, collections, "comparison")
    raw = table().replace(MISSING, "הבדל [A1, B1]")
    path = "responses/comparison.txt"
    dump_text(run.root/path, raw)
    dump_json(run.root/"contexts/comparison.json", ctx)
    dump_json(run.root/"prompts/comparison.json", dict(model="fixture", stream=False, messages=[
        dict(role="system", content=SYSTEM), dict(role="user", content=comparison_prompt(companies,ctx["text"],DIMENSIONS,version=1))]))
    group = [dict(attempt=1, success=True, output_path=path)]
    run.log("validation_failed", operation="comparison", attempt=1, reason="unknown, malformed or out-of-context citation")
    details, action = writing_checkpoint(*args, group, run_events(run.root))
    assert action == "revalidate_saved" and not (run.root/"artifacts/comparison.md").exists()
    run.log("saved_response_revalidated", operation="comparison", output_path=path)
    export(run, "comparison", raw, details)
    assert writing_checkpoint(*args, group, run_events(run.root)) == (details, None)
    assert (run.root/"artifacts/comparison.md").read_bytes() == (run.root/path).read_bytes()


def test_regenerate_measured_short_body_then_resume_only_partial_stream(tmp_path):
    a, b = "https://a.test/", "https://b.test/"
    settings = Settings((Company("A","A",a), Company("B","B",b)), output_dir=tmp_path, provider_retries=0)
    def reply(text):
        return N(choices=[N(message=N(content=text), finish_reason="stop")])
    short = brochure("A1", a, 154)
    create = Mock(side_effect=[reply('{"links":[]}'),reply('{"links":[]}'),reply(short),
                               reply(brochure("A1",a,250)), reply(brochure("A1",a)), reply(brochure("B1",b)),
                               iter([event("קטע\r\nשנקטע")]),reply(table()),reply(brochure("A1",a))])
    client = N(chat=N(completions=N(create=create)))
    with pytest.raises(RuntimeError, match="missing finish event"):
        run_workflow(settings, client, fetch=Mock(side_effect=[Page(a,"ok",text="x"*1300),Page(b,"ok",text="y"*1300)]),
                     show=lambda _: None, mode="fixture")
    root = next(tmp_path.iterdir())
    first = read_json(root/"prompts/A_customers.json")["messages"]
    second = read_json(root/"prompts/A_customers.attempt2.json")["messages"]
    assert first[0] == second[0] and second[1]["content"].endswith(first[1]["content"])
    assert "154" in second[1]["content"] and "240–260" in second[1]["content"]
    assert (root/"contexts/A_customers.json").read_bytes() == (root/"contexts/A_customers.attempt2.json").read_bytes()
    assert (root/"responses/A_customers.txt").read_text("utf-8") == short
    assert read_json(root/"metadata/A_customers.json")["word_count"] == 250
    assert any(e.get("reason") == "word count 154 outside 200–300" for e in run_events(root) if e["event"] == "retry")
    partial = root/"responses/B_candidates.txt"
    assert partial.read_bytes() == "קטע\r\nשנקטע".encode()
    error = read_json(root/"responses/B_candidates_error.json")
    assert error["stream_metadata"]["finish_reason"] is None and not error["retryable"]
    log = (root/"execution_log.jsonl").read_bytes()
    assert list(resume_workflow(root, settings, inspect=True)["resume_attempts"]) == ["B_candidates"]
    create.side_effect = [iter([event(brochure("B1",b,250)),event(finish="stop")])]
    updates = []
    resume_workflow(root, settings, make_client=lambda _:client, fetch=Mock(side_effect=AssertionError),
                    show=lambda _:None, update=updates.append)
    assert partial.read_bytes() == "קטע\r\nשנקטע".encode() and (root/"execution_log.jsonl").read_bytes().startswith(log)
    assert updates[-1] == brochure("B1",b,250) and create.call_count == 10
    assert replay(root)["B_candidates"] == dict(word_count=250, cited=["B1"], accepted_attempt=2)
