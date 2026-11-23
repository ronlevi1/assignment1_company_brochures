"""Offline SDK-status and checkpoint regressions. All responses and credentials are fixtures."""
import json
from dataclasses import replace
from types import SimpleNamespace as N
from unittest.mock import Mock, call, patch
from zipfile import ZipFile

import httpx
import pytest
from openai import BadRequestError, InternalServerError

from config import Company, Settings, client_for
from evaluation import accepted_text
from llm_service import ModelService
from package_project import build_zip
from prompt_builder import LEGACY_SELECT_SYSTEM
from scraper import Page
from source_manager import validate_selection
from storage import Run, dump_json, read_json
from workflow import generate, replay, reselect_links, resume_workflow, run_events, run_workflow, saved_links_step, start_run
from test_outputs import brochure, table, event


def status_error(code, message="fixture provider failure", *, wrapped=False):
    body = {"code": code, "message": message, "status": "UNAVAILABLE" if code == 503 else "FIXTURE"}
    request = httpx.Request("POST", "https://fixture.test/v1/chat/completions",
                            headers={"Authorization": "Bearer private-request-value"})
    response = httpx.Response(code, request=request, json={"error": body},
                              headers={"x-request-id": "fixture-request-id", "authorization": "private-header"})
    error_type = BadRequestError if code == 400 else InternalServerError
    return error_type("raw SDK exception: " + message, response=response, body=[{"error": body}] if wrapped else body)


def response(text):
    return N(choices=[N(message=N(content=text), finish_reason="stop")], id="test-completion")


FENCED_EMPTY = "```json\n{\n  \"links\": []\n}\n```"


@pytest.mark.parametrize(("raw", "error"), [
    (FENCED_EMPTY, "Markdown code fence"),
    ('{"links":[]}', None),
    ('{"links":[}', "Expecting value"),
    ('{"links":[]}\ntrailing commentary', "Extra data"),
    ('{"links":[],"links":[]}', "duplicate JSON field"),
    (json.dumps({"links": [dict(type="about", url="https://a.test/about", reason="team"),
                           dict(type="legal", url="https://a.test/privacy", reason="policy")]}), "forbidden"),
])
def test_exact_selection_document(raw, error):
    candidates = ["https://a.test/about", "https://a.test/privacy"]
    if error:
        with pytest.raises(ValueError, match=error):
            validate_selection(raw, candidates, "https://a.test/")
    else:
        assert validate_selection(raw, candidates, "https://a.test/") == []


@pytest.mark.parametrize("links", [
    [],
    [dict(type="features", url="https://a.test/features", reason="Customers can check which metrics are available."),
     dict(type="about", url="https://a.test/about", reason="Job candidates can look for team background.")],
])
def test_reselect_rejected_legacy_request_in_separate_run(setup, links):
    settings, _, client, create = setup
    settings = replace(settings, model="gemini-3.5-flash-lite",
                       base_url="https://generativelanguage.googleapis.com/v1beta/openai/", provider_retries=0)
    source = start_run(settings, "fixture")
    old_config = read_json(source.root / "config.json")
    del old_config["selection_version"]
    dump_json(source.root / "config.json", old_config)
    create.side_effect = [response(FENCED_EMPTY), response(json.dumps({"links": links}))]
    home = Page(settings.companies[0].url, "ok", text="fixture "*200, hrefs=["/about", "/features"])
    with pytest.raises(RuntimeError, match="Markdown code fence"):
        generate(source, settings, client, fetch=Mock(return_value=home))
    old_request = create.call_args.kwargs
    assert old_request["messages"][0]["content"] == LEGACY_SELECT_SYSTEM and "response_format" not in old_request
    original = {p: p.read_bytes() for p in source.root.rglob("*") if p.is_file()}
    assert read_json(source.root / "data/A_selection.json")["valid"] is False
    assert (source.root / "responses/A_links.txt").read_text("utf-8") == FENCED_EMPTY
    factory = Mock(return_value=client)
    with patch("workflow.fetch_website_contents", side_effect=AssertionError("unexpected website fetch")):
        preview = reselect_links(source.root, settings, inspect=True, make_client=factory)
        factory.assert_not_called()
        new = reselect_links(source.root, settings, make_client=factory)
        assert saved_links_step(new, settings, make_client=factory) == new / "data/A_selection.json"
    factory.assert_called_once()
    assert create.call_count == 2 and new != source.root
    assert {p: p.read_bytes() for p in source.root.rglob("*") if p.is_file()} == original
    request = create.call_args.kwargs
    assert request == read_json(new / "prompts/A_links.json")
    assert request["model"] == settings.model and request["stream"] is False
    assert request["messages"][0]["content"] == preview["system"] != LEGACY_SELECT_SYSTEM
    assert request["messages"][1] == old_request["messages"][1]
    fmt = request["response_format"]
    assert fmt == preview["response_format"] and fmt["type"] == "json_schema"
    schema = fmt["json_schema"]["schema"]["properties"]["links"]
    assert schema.get("minItems", 0) == 0 and schema["maxItems"] == 3
    assert set(schema["items"]["required"]) == {"type", "url", "reason"}
    assert next(e for e in run_events(new) if e["event"] == "llm")["parameters"]["response_format"] == fmt
    assert read_json(new / "data/A_selection.json") == dict(raw=json.dumps({"links": links}), valid=True, reason="", links=links)
    assert read_json(new / "config.json")["source_run_id"] == source.id
    with pytest.raises(ValueError, match="rejected"):
        reselect_links(new, settings, make_client=factory)
    factory.assert_called_once()


@pytest.fixture
def setup(tmp_path):
    companies = tuple(Company(c, "Fixture " + c, f"https://{c.lower()}.test/") for c in "AB")
    settings = Settings(companies, model="fixture-model", base_url="https://fixture.test/v1", output_dir=tmp_path)
    run = Run.new(tmp_path)
    create = Mock()
    client = N(chat=N(completions=N(create=create)), api_key="private-client-value")
    return settings, run, client, create


@pytest.mark.parametrize("code", [500, 502, 503, 504])
def test_retry_success_records_each_physical_call(setup, code):
    settings, run, client, create = setup
    create.side_effect = [status_error(code, wrapped=True), response('{"links":[]}')]
    service = ModelService(client, settings, run)
    with patch("llm_service.sleep") as sleep:
        assert service.call("A_links", "A", "both", "system", "user", {"text": "abc"}) == '{"links":[]}'
    sleep.assert_called_once_with(1)
    events = run_events(run.root)
    assert [e["event"] for e in events] == ["llm_started", "llm", "retry", "llm_started", "llm"]
    first, retry, last = events[1], events[2], events[4]
    assert (first["attempt"], retry["attempt"], last["attempt"]) == (1, 2, 2)
    assert retry["reason"] == f"HTTP {code}"
    assert first["http_status"] == first["provider_code"] == code
    assert first["response_metadata"]["x-request-id"] == "fixture-request-id"
    assert first["run_id"] == run.id and first["operation"] == "A_links" and first["duration_s"] >= 0
    assert first["parameters"] == dict(model=settings.model, stream=False, timeout_s=settings.timeout)
    assert first["provider_message"] == "fixture provider failure"
    assert read_json(run.root / first["output_path"])["provider_status"] == first["provider_status"]
    assert last["success"] and last["response_metadata"]["id"] == "test-completion"
    for field in ("input_path", "context_path"):
        assert first[field] != last[field]
        assert (run.root / first[field]).read_bytes() == (run.root / last[field]).read_bytes()
    assert create.call_args_list == [call(**read_json(run.root / e["input_path"])) for e in [first, last]]


@pytest.mark.parametrize("limit", [0, 1, 2, 3])
def test_exhaustion_preserves_attempts(setup, limit):
    settings, run, client, create = setup
    create.side_effect = status_error(503)
    service = ModelService(client, replace(settings, provider_retries=limit), run)
    with patch("llm_service.sleep") as sleep, pytest.raises(InternalServerError):
        service.call("A_links", "A", "both", "system", "user", {})
    assert sleep.call_args_list == [call(n) for n in [1, 2, 4][:limit]]
    ended = [e for e in run_events(run.root) if e["event"] == "llm"]
    assert len(ended) == create.call_count == limit + 1
    assert {e["attempt"] for e in ended} == set(range(1, limit+2))
    assert len(list((run.root/"responses").glob("*_error.json"))) == len(ended)
    assert all(not e["success"] and e["http_status"] == 503 for e in ended)


def test_configuration_and_sdk_retries(setup, monkeypatch):
    settings, *_ = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret")
    with client_for(settings) as client:
        assert client.max_retries == 0 and client.timeout == settings.timeout
    monkeypatch.setenv("PROVIDER_RETRIES", "4")
    monkeypatch.setenv("CONFIG_DIR", str(settings.output_dir))
    with pytest.raises(ValueError, match="PROVIDER_RETRIES"):
        Settings.load()


def test_permanent_error_and_redaction_including_cli_summary(setup, monkeypatch):
    settings, _, client, create = setup
    monkeypatch.setenv("OPENAI_API_KEY", "private-env-value")
    create.side_effect = status_error(400, "Invalid field; private-client-value private-env-value "
                                      "Authorization: Bearer private-bearer-value key=private-query-value")
    fetch = Mock(return_value=Page(settings.companies[0].url, "ok", text="fixture", hrefs=["/team"]))
    with pytest.raises(RuntimeError, match="A_links attempt 1.*HTTP 400") as error:
        run_workflow(settings, client, fetch=fetch)
    create.assert_called_once()
    fetch.assert_called_once()
    root = next(settings.output_dir.glob("*/config.json")).parent
    diagnostics = str(error.value) + "".join(p.read_text("utf-8") for p in root.rglob("*") if p.is_file())
    assert "Invalid field" in diagnostics and "[REDACTED]" in diagnostics
    assert "private-" not in diagnostics and "authorization" not in diagnostics.lower()
    factory = Mock()
    with pytest.raises(ValueError, match="5xx"):
        saved_links_step(root, settings, make_client=factory)
    with pytest.raises(ValueError, match="non-retryable"):
        resume_workflow(root, settings, make_client=factory)
    factory.assert_not_called()


def stop_at_links(settings, client, create):
    create.side_effect = status_error(500)
    home = settings.companies[0].url
    fetch = Mock(return_value=Page(home, "ok", text="fixture " * 200, hrefs=["/team/"]))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        run_workflow(replace(settings, provider_retries=0), client, fetch=fetch)
    fetch.assert_called_once()
    return next(settings.output_dir.glob("*/config.json")).parent


@pytest.mark.parametrize("raw", ["not JSON", '{"links":[{"type":"team","url":"https://outside.test/","reason":"fixture"}]}'])
def test_invalid_selection_never_resampled(setup, raw):
    settings, _, client, create = setup
    root = stop_at_links(settings, client, create)
    create.side_effect = [response(raw)]
    with pytest.raises(RuntimeError), patch("workflow.fetch_website_contents") as fetch:
        saved_links_step(root, settings, make_client=lambda _: client)
    assert not fetch.called
    assert not read_json(root / "data/A_selection.json")["valid"]
    assert (root / "responses/A_links.attempt2.txt").read_text("utf-8") == raw
    factory = Mock()
    with pytest.raises(ValueError):
        saved_links_step(root, settings, make_client=factory)
    factory.assert_not_called()
    assert create.call_count == 2  # one original 500, one invalid completion


@pytest.mark.parametrize("gemini", [False, True])
def test_checkpoint_and_continuation_with_mixed_retries(setup, gemini):
    settings, _, client, create = setup
    if gemini:
        settings = replace(settings, base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                           model="gemini-3.5-flash-lite")
    root = stop_at_links(settings, client, create)
    original = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    old_log = original.pop(root / "execution_log.jsonl")
    factory = Mock(return_value=client)
    assert saved_links_step(root, settings, inspect=True, make_client=factory)["candidates"] == 1
    with pytest.raises(ValueError, match="validated"):
        saved_links_step(root, settings, continue_run=True, make_client=factory)
    factory.assert_not_called()
    selection = json.dumps({"links": [dict(type="team", url="https://a.test/team", reason="fixture")]})
    create.side_effect = [status_error(503), response(selection)]
    with patch("llm_service.sleep"), patch("workflow.fetch_website_contents", side_effect=AssertionError):
        path = saved_links_step(root, settings, make_client=factory)
        assert path == saved_links_step(root, settings, make_client=factory)
    assert factory.call_count == 1
    assert all(p.read_bytes() == data for p, data in original.items())
    assert (root / "execution_log.jsonl").read_bytes().startswith(old_log)
    assert (root / "prompts/A_links.attempt3.json").read_bytes() == original[root / "prompts/A_links.json"]
    assert read_json(path)["raw"] == selection

    a, b = (c.url for c in settings.companies)
    fetch = Mock(side_effect=[Page(a+"team/", "ok", text="team"), Page(b, "ok", text="fixture "*200)])
    create.side_effect = [
        response('{"links":[]}'),  # B_links
        status_error(502), response("invalid prose"), status_error(504), response(brochure("A1", a)),
        response(brochure("A1", a)), response(brochure("B1", b)),
        iter([event(brochure("B1", b)), event(finish="stop")]), response(table()), response(brochure("A1", a))]
    with patch("llm_service.sleep"):
        assert saved_links_step(root, settings, continue_run=True, make_client=factory,
                                fetch=fetch, show=lambda _: None) == root
    assert fetch.call_args_list == [call(a+"team/", a, additional=True), call(b, b)]
    assert [e["attempt"] for e in run_events(root) if e["event"] == "llm" and e["operation"] == "A_links"] == [1, 2, 3]
    assert replay(root)["A_customers"]["accepted_attempt"] == 4
    for invocation in create.call_args_list:
        request = invocation.kwargs
        is_selection = "Candidate URLs:" in request["messages"][1]["content"]
        assert ("response_format" in request) == (gemini and is_selection)
    assert accepted_text(root, "A_customers") == brochure("A1", a)
    assert (root / "responses/A_customers.attempt2.txt").read_text("utf-8") == "invalid prose"
    archive_path = root.parent / "recovered-for-review.zip"
    build_zip(archive_path, root, for_review=True)
    with ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        for name in ("responses/A_links_error.json", "responses/A_links.attempt3.txt",
                     "responses/A_customers.attempt3_error.json", "responses/A_customers.attempt4.txt"):
            assert archive.read(f"assignment1_company_brochures/runs/{root.name}/{name}") == (root/name).read_bytes()
        assert not any(name.endswith("/.env") for name in archive.namelist())
    with pytest.raises(ValueError, match="stopped at A_links"):
        saved_links_step(root, settings, continue_run=True, make_client=factory)
    assert factory.call_count == 2
    dump_json(root / "contexts/A_customers.attempt3.json", {"text": "changed"})
    with pytest.raises(ValueError, match="inputs changed"):
        replay(root)


def test_checkpoint_rejects_changed_inputs_before_client(setup):
    settings, _, client, create = setup
    root = stop_at_links(settings, client, create)
    factory = Mock()
    with pytest.raises(ValueError, match="configuration differs"):
        saved_links_step(root, replace(settings, model="different"), make_client=factory)
    dump_json(root / "data/A_candidates.json", ["https://outside.test/"])
    with pytest.raises(ValueError, match="candidates"):
        saved_links_step(root, settings, make_client=factory)
    factory.assert_not_called()


def test_legacy_error_keeps_unknown_status_and_original_bytes(setup):
    settings, _, client, create = setup
    root = stop_at_links(settings, client, create)
    # The original format predates start events and detailed error records.
    logs = [e for e in run_events(root) if e["event"] != "llm_started"]
    old = next(e for e in logs if e["event"] == "llm")
    for key in ("http_status", "provider_code", "provider_status", "provider_message", "response_metadata",
                "parameters", "error_path", "retryable"):
        del old[key]
    log_path = root / "execution_log.jsonl"
    log_path.write_text("".join(json.dumps(e)+"\n" for e in logs), encoding="utf-8")
    error_path = root / old["output_path"]
    dump_json(error_path, {"error": "InternalServerError"})
    config = read_json(root / "config.json")
    del config["provider_retries"]
    dump_json(root / "config.json", config)
    snapshot = log_path.read_bytes(), error_path.read_bytes()
    assert saved_links_step(root, settings, inspect=True)["http_status"] is None
    create.side_effect = [response('{"links":[]}')]
    saved_links_step(root, settings, make_client=lambda _: client)
    assert log_path.read_bytes().startswith(snapshot[0])
    assert error_path.read_bytes() == snapshot[1]
    assert saved_links_step(root, settings, inspect=True)["attempt"] == 2


def test_interrupted_stream_retains_text_and_diagnostics_without_retry(setup):
    settings, run, client, create = setup
    def interrupted():
        yield event("fixture partial")
        raise status_error(503)
    create.return_value = interrupted()
    with pytest.raises(InternalServerError):
        ModelService(client, settings, run).call("B_candidates", "B", "candidates", "sys", "user", {}, lambda _: None)
    create.assert_called_once()
    last = run_events(run.root)[-1]
    assert last["http_status"] == 503 and last["status"] == "partial" and not last["retryable"]
    assert (run.root / last["output_path"]).read_text("utf-8") == "fixture partial"
    assert read_json(run.root / last["error_path"])["provider_code"] == 503


def test_later_failure_retains_completed_company(setup):
    settings, _, client, create = setup
    first = '{"links":[]}'
    create.side_effect = [response(first), status_error(503)]
    fetch = Mock(side_effect=[Page(c.url, "ok", text="fixture "*200) for c in settings.companies])
    with pytest.raises(RuntimeError, match="B_links attempt 1.*HTTP 503"):
        run_workflow(replace(settings, provider_retries=0), client, fetch=fetch)
    root = next(settings.output_dir.glob("*/config.json")).parent
    assert read_json(root / "data/A_selection.json") == dict(raw=first, links=[], valid=True, reason="")
    assert read_json(root / "data/A_sources.json")[0]["text"] == "fixture "*200
    assert (root / "responses/A_links.txt").read_text("utf-8") == first
    assert (root / "responses/B_links_error.json").is_file()


def remaining_writing(settings):
    a, b = (c.url for c in settings.companies)
    return [
        response(brochure("A1", a)), response(brochure("A1", a)),
        response(brochure("B1", b)), iter([event(brochure("B1", b)), event(finish="stop")]),
        response(table()), response(brochure("A1", a)),
    ]


def test_stage_resume_from_validated_selection(setup):
    settings, _, client, create = setup
    a, b = (c.url for c in settings.companies)
    root = stop_at_links(settings, client, create)
    create.side_effect = [response(json.dumps({"links": [dict(type="team", url=a+"team", reason="team")]}))]
    saved_links_step(root, settings, make_client=lambda _: client)
    selection = (root / "data/A_selection.json").read_bytes()
    prior_calls = create.call_count
    create.side_effect = [response('{"links":[]}'), *remaining_writing(settings)]
    fetch = Mock(side_effect=[Page(a+"team/", "ok", text="team"), Page(b, "ok", text="fixture "*200)])
    assert resume_workflow(root, settings, inspect=True)["stages"]["A"] == "fetch_selected"
    assert resume_workflow(root, settings, make_client=lambda _: client, fetch=fetch, show=lambda _: None) == root
    assert fetch.call_args_list == [call(a+"team/", a, additional=True), call(b, b)]
    assert create.call_count == prior_calls + 7
    assert (root / "data/A_selection.json").read_bytes() == selection
    assert len(replay(root)) == 6


def test_stage_resume_after_validation_exhaustion_and_repeated_503(setup):
    settings, _, client, create = setup
    a, b = (c.url for c in settings.companies)
    create.side_effect = [response('{"links":[]}'), response('{"links":[]}'),
                          status_error(503), response("short first draft"), status_error(503), response("short second draft"),
                          response("short candidate draft"), status_error(503), status_error(503), status_error(503)]
    with patch("llm_service.sleep"), pytest.raises(RuntimeError, match="A_candidates attempt 4.*HTTP 503"):
        run_workflow(settings, client, fetch=Mock(side_effect=[Page(a, "ok", text="x"*1400),
                                                               Page(b, "ok", text="y"*1500)]), show=lambda _: None)
    root = next(settings.output_dir.glob("*/config.json")).parent
    original = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    history = original.pop(root / "execution_log.jsonl")
    factory = Mock(return_value=client)
    plan = resume_workflow(root, settings, inspect=True, make_client=factory)
    factory.assert_not_called()
    assert plan["stages"]["A"] == plan["stages"]["B"] == "reuse"
    assert {op: d["attempt"] for op, d in plan["resume_attempts"].items()} == {"A_customers": 5, "A_candidates": 5}
    assert (root / "execution_log.jsonl").read_bytes() == history
    never_fetch = Mock(side_effect=AssertionError("repeated collection"))
    settings = replace(settings, provider_retries=0)
    create.side_effect = [response(brochure("A1", a)), status_error(503)]
    with pytest.raises(RuntimeError, match="A_candidates attempt 5.*HTTP 503"):
        resume_workflow(root, settings, make_client=factory, fetch=never_fetch, show=lambda _: None)
    assert resume_workflow(root, settings, inspect=True)["stages"]["A_customers"] == "reuse"
    accepted = root / "artifacts/brochures/A_customers.md"
    original[accepted] = accepted.read_bytes()
    create.side_effect = remaining_writing(settings)[1:]
    assert saved_links_step(root, settings, continue_run=True, make_client=factory, fetch=never_fetch, show=lambda _: None) == root
    never_fetch.assert_not_called()
    assert create.call_count == 17 and factory.call_count == 2
    results = replay(root)
    assert results["A_customers"]["accepted_attempt"] == 5 and results["A_candidates"]["accepted_attempt"] == 6
    assert all(p.read_bytes() == data for p, data in original.items())
    assert (root / "execution_log.jsonl").read_bytes().startswith(history)
    grants = [e for e in run_events(root) if e.get("kind") == "stage_resume"]
    assert [(e["operation"], e["attempt"]) for e in grants] == [("A_customers", 5), ("A_candidates", 5), ("A_candidates", 6)]
    assert resume_workflow(root, settings, make_client=factory) == root
    assert factory.call_count == 2


def test_stage_resume_of_alternative_and_b_selection(setup):
    settings, _, client, create = setup
    settings = replace(settings, provider_retries=0)
    a, b = (c.url for c in settings.companies)
    def choose(url):
        return response(json.dumps({"links": [dict(type="team", url=url, reason="team evidence")]}))
    create.side_effect = [choose(a+"one"), status_error(503)]
    first = Mock(side_effect=[Page(a, "ok", text="short", hrefs=["/one", "/two"]), Page(a+"one","ok", text="short")])
    with pytest.raises(RuntimeError, match="A_alternative attempt 1"):
        run_workflow(settings, client, fetch=first, show=lambda _: None)
    root = next(settings.output_dir.glob("*/config.json")).parent
    assert resume_workflow(root, settings, inspect=True)["stages"]["A"] == "select_alternative"
    create.side_effect = [choose(a+"two"), status_error(503)]
    after_a = Mock(side_effect=[Page(a+"two", "ok", text="team"), Page(b, "ok", text="y"*1600)])
    with pytest.raises(RuntimeError, match="B_links attempt 1"):
        resume_workflow(root, settings, make_client=lambda _: client, fetch=after_a, show=lambda _: None)
    assert after_a.call_args_list == [call(a+"two", a, additional=True), call(b, b)]
    plan = resume_workflow(root, settings, inspect=True)
    assert (plan["stages"]["A"], plan["stages"]["B"]) == ("reuse", "select")
    create.side_effect = [response('{"links":[]}'), *remaining_writing(settings)]
    resume_workflow(root, settings, make_client=lambda _: client, fetch=Mock(side_effect=AssertionError),
                    show=lambda _: None)
    assert len(replay(root)) == 6


def test_tampered_export_blocks_resume_before_any_new_call(setup):
    settings, _, client, create = setup
    settings = replace(settings, provider_retries=0)
    a, b = (c.url for c in settings.companies)
    create.side_effect = [response('{"links":[]}'), response('{"links":[]}'), response(brochure("A1", a)), status_error(503)]
    with pytest.raises(RuntimeError, match="A_candidates"):
        run_workflow(settings, client, fetch=Mock(side_effect=[Page(a,"ok",text="x"*1400), Page(b,"ok",text="y"*1400)]),
                     show=lambda _: None)
    root = next(settings.output_dir.glob("*/config.json")).parent
    (root / "artifacts/brochures/A_customers.md").write_text("altered", encoding="utf-8")
    log = (root / "execution_log.jsonl").read_bytes()
    factory = Mock()
    with pytest.raises(ValueError, match="artifact differs"):
        resume_workflow(root, settings, make_client=factory)
    assert (root / "execution_log.jsonl").read_bytes() == log
    factory.assert_not_called()


def test_explicit_resume_of_rejected_writing_limits_new_samples(setup):
    settings, _, client, create = setup
    settings = replace(settings, provider_retries=0)
    a, b = (c.url for c in settings.companies)
    create.side_effect = [response('{"links":[]}'), response('{"links":[]}'), response("short"), response("short"),
                          *remaining_writing(settings)[1:]]
    with pytest.raises(RuntimeError, match="Unaccepted outputs"):
        run_workflow(settings, client, fetch=Mock(side_effect=[Page(a,"ok",text="x"*1400), Page(b,"ok",text="y"*1400)]),
                     show=lambda _: None)
    root = next(settings.output_dir.glob("*/config.json")).parent
    prior_count = create.call_count
    factory = Mock(return_value=client)
    create.side_effect = [response("still short")]
    with pytest.raises(RuntimeError, match="Unaccepted outputs"):
        resume_workflow(root, settings, make_client=factory, fetch=Mock(side_effect=AssertionError), show=lambda _: None)
    assert create.call_count == prior_count + 1
    create.side_effect = [response(brochure("A1", a))]
    resume_workflow(root, settings, make_client=factory, fetch=Mock(side_effect=AssertionError), show=lambda _: None)
    assert create.call_count == prior_count + 2
    assert replay(root)["A_customers"]["accepted_attempt"] == 4
