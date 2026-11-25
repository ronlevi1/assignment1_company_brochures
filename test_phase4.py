"""Offline checks for Phase 4 formatting, streaming, and the prompt experiment."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

import generate_outputs as generation
from utils import validate_output


URL = "https://example.org/product"


@pytest.mark.parametrize("words, valid", [(199, False), (200, True), (300, True), (301, False)])
def test_word_count(words, valid):
    body = "כותרת\n" + "מילה " * (words - 2) + "[A1]"
    report = validate_output(body + f"\n## מקורות\n[A1] {URL}", {"A1": URL})
    assert (report["word_count"], report["valid"]) == (words, valid)


@pytest.mark.parametrize("citation", ["[B1]", "[A99]", "[X1]", "[A1, B1]"])
def test_unknown_or_malformed_citation(citation):
    report = validate_output(f"טענה [A1] {citation}", {"A1": URL}, brochure=False)
    assert any("Unknown source IDs" in error for error in report["errors"])


def test_grouped_citations_match_the_individual_source_list():
    body = "מילה " * 200 + "[A1, A3]"
    footer = f"\n## מקורות\n[A1] {URL}\n[A3] {URL}/about"
    sources = {"A1": URL, "A3": URL + "/about"}
    assert validate_output(body + footer, sources)["valid"]
    bad = validate_output(body.replace("A3]", "A3, typo]") + footer, sources)
    assert any("Malformed citation" in error for error in bad["errors"])


def test_source_list_allows_extra_context_sources_but_checks_each_url():
    body = "מילה " * 200 + "[B1]\n## מקורות\n"
    sources = {"B1": URL, "B4": URL + "/about"}
    used = f"[B1] {URL}\n"
    extra = f"[B4] {URL}/about"
    assert validate_output(body + used + extra, sources)["valid"]
    for footer in [extra, used + f"[B4] {URL}", used + f"[B9] {URL}/about"]:
        assert not validate_output(body + footer, sources)["valid"]


def test_comparison_has_four_rows_and_conclusion_without_brochure_limits():
    table = "| ממד | א | ב |\n| --- | --- | --- |\n" + "| ממד | [A1] | [B1, B2] |\n" * 4
    sources = dict.fromkeys(["A1", "B1", "B2"], URL)
    assert validate_output(table + "\nסיכום", sources, brochure=False)["valid"]
    assert not validate_output(table, sources, brochure=False)["valid"]
    assert not validate_output("סיכום [A1]", sources, brochure=False)["valid"]


def test_baseline_and_improved_share_context_and_settings():
    context = "Exact source text\n[A1] Example\n" + URL + "\nOriginal."
    record = {"context": context, "allocations": [{"source_id": "A1", "used_chars": 9}]}
    source = {"title": "Example", "url": URL}
    with patch.object(generation, "read_json", side_effect=[record, source, record, source]):
        improved = generation.prepare("A-customer")
        baseline = generation.prepare("A-customer-baseline")
    assert improved["messages"][1] == baseline["messages"][1] == {"role": "user", "content": context}
    for key in ("model", "sources", "audience", "company", "stream", "context_path"):
        assert improved[key] == baseline[key]
    assert improved["messages"][0] != baseline["messages"][0]


@pytest.mark.parametrize("interrupted", [False, True])
def test_stream_persists_exact_accumulation(interrupted, capsys):
    root = Path.cwd().resolve()
    run = root / (".phase4-test-" + uuid4().hex)
    run.mkdir()
    folder = run / "B-candidate"
    inputs = dict(action="B-candidate", company="B", audience="candidate", model="test",
                  stream=True, messages=[], sources={"B1": URL})
    body = "עבודה " * 199 + "[B1]"
    footer = f"\n## מקורות\n[B1] {URL}"

    def events():
        for piece in [[], None, body, "", footer]:
            event = Mock(usage=None)
            event.choices = [] if piece == [] else [
                SimpleNamespace(delta=SimpleNamespace(content=piece), finish_reason="stop" if piece == footer else None)
            ]
            event.model_dump_json.return_value = json.dumps({"piece": piece})
            yield event
            if interrupted and piece == body:
                raise ConnectionError("simulated interruption")

    try:
        client = Mock()
        client.chat.completions.create.return_value = events()
        text = generation.generate(client, inputs, folder)
        assert text == (body if interrupted else body + footer)
        assert capsys.readouterr().out.startswith(text)
        assert (folder / "output.md").read_bytes() == text.encode()
        state = generation.read_json(folder / "result.json")
        assert state["status"] == ("partial" if interrupted else "complete")
        assert len((folder / "events.jsonl").read_text().splitlines()) == (3 if interrupted else 5)
        assert "usage" not in state
        client.chat.completions.create.assert_called_once()
    finally:
        assert run.resolve().parent == root
        shutil.rmtree(run)
