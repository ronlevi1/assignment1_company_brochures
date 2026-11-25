"""Offline checks for Phase 3 using synthetic sources and HTTP responses."""

import json
import shutil
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
import requests

import collect_sources as phase3


def source(sid, text, status="ok"):
    return dict(source_id=sid, company_id=sid[0], title=f"Title {sid}",
                url=f"https://{sid[0].lower()}.example/{sid}", retrieved_at="saved",
                text=text, status=status)


def test_complete_text_and_metadata():
    s = source("A1", "  Unicode café\n")
    result = phase3.build_context([s], len(s["text"]))
    assert result["context"] == f"{phase3.INSTRUCTIONS}\n\n[A1] Title A1\n{s['url']}\n{s['text']}"
    assert result["allocations"][0]["action"] == "included"


def test_empty_and_failed_sources():
    result = phase3.build_context([source("A1", "", "empty"), source("A2", "Error page", "failed"),
                                   source("A3", "  ")])
    assert result["context"] == phase3.INSTRUCTIONS
    assert result["used_chars"] == 0
    assert [row["reason"] for row in result["allocations"]] == ["empty", "failed", "Empty text"]


def test_fair_allocation_keeps_source_order_and_originals():
    sources = [source("A1", "x" * 20000), source("A2", "abc"), source("A3", "y" * 20000)]
    result = phase3.build_context(sources, 11)
    assert [(r["source_id"], r["used_chars"], r["action"]) for r in result["allocations"]] == [
        ("A1", 4, "truncated"), ("A2", 3, "included"), ("A3", 4, "truncated")]
    assert result["used_chars"] == 11
    assert len(sources[0]["text"]) == 20000
    for s in sources:
        assert f"[{s['source_id']}] {s['title']}\n{s['url']}" in result["context"]
    assert result["context"].startswith(phase3.INSTRUCTIONS)


@pytest.mark.parametrize("budget", [0, 1, 12000])
def test_comparison_shares_one_budget(budget):
    sources = [source("A1", "a" * 15000), source("B1", "b" * 15000)]
    result = phase3.build_context(sources, budget)
    a, b = [r["used_chars"] for r in result["allocations"]]
    assert a + b == result["used_chars"] == budget
    assert abs(a - b) <= 1
    assert result["context"].count("a" * 15000) == 0


def test_collection_saves_only_planned_requests():
    root = Path.cwd().resolve()
    output = root / (".phase3-test-" + uuid4().hex)
    home = source("A1", "Original homepage")
    links = [{"url": f"https://a.example/{i}"} for i in range(2, 5)]
    replies = [
        Mock(status_code=200, content=b'<body>Product<a href="/extra"></a></body>'),
        Mock(status_code=200, content=b"<body></body>"),
        requests.Timeout(),
    ]
    try:
        with patch.object(phase3.requests, "get", side_effect=replies) as get:
            phase3.collect({"A": (home, links)}, output)
        assert [call.args[0] for call in get.call_args_list] == [link["url"] for link in links]
        assert all(call.kwargs["allow_redirects"] is False for call in get.call_args_list)
        assert phase3.read_json(output / "A1.json") == home
        log = [json.loads(line) for line in (output / "requests.jsonl").read_text().splitlines()]
        assert [(r["source_id"], r["status"], r["reason"]) for r in log] == [
            ("A2", "ok", None), ("A3", "empty", "No readable body text"), ("A4", "failed", "Timeout")]
        for row in log:
            assert phase3.read_json(Path(row["output_path"]))["status"] == row["status"]
        assert phase3.read_json(output / "context_comparison.json") == phase3.read_json(output / "context_A.json")
    finally:
        if output.resolve().parent == root and output.is_dir():
            shutil.rmtree(output)
