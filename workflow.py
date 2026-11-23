"""The original Day 5 steps in a fixed order, with one persistent run per invocation."""
import argparse
import json
import socket
from shutil import copyfile
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
from pathlib import Path
from datetime import datetime
from urllib.parse import urlsplit

import requests

from config import Company, Settings, client_for
from context_manager import build_context
from evaluation import MAIN, PROTOCOL, prepare_review, read_text, publish_review
from llm_service import ModelService, TRANSIENT, safe_text
from prompt_builder import (SYSTEM, LEGACY_SYSTEM, comparison_prompt, link_prompt, get_brochure_user_prompt,
                            length_feedback, selection_args)
from scraper import Page, fetch_website_contents, fetch_website_links
from source_manager import (collect_selected, fetch_page_and_all_relevant_links, finish_collection, save_selection,
                            validate_selection, alternative_plan)
from storage import Run, attempt_key, dump_json, dump_text, read_json
from url_utils import candidate_urls, normalize_url, forbidden
from validators import validate_brochure, validate_comparison


def select_relevant_links(service, company, candidates):
    context = json.dumps(candidates, ensure_ascii=False, indent=2)
    return service.call(f"{company.id}_links", company.id, "both", user=link_prompt(company, context),
                        context={"text": context, "candidates": candidates},
                        **selection_args(read_json(service.run.root / "config.json")))


def saved_sources(root, cid):
    return read_json(root / "data" / f"{cid}_sources.json")


def alternative_messages(company, plan):
    context = {**plan, "text": json.dumps(plan["candidates"], ensure_ascii=False, indent=2)}
    user = (f"Evidence gap: {plan['reason']} Select up to {plan['remaining']} unused pages. "
            f"Address this gap in each reason.\n" + link_prompt(company, context["text"]))
    return user, context


def select_alternative(service, company, plan):
    user, context = alternative_messages(company, plan)
    return service.call(f"{company.id}_alternative", company.id, "both", user=user, context=context,
                        **selection_args(read_json(service.run.root / "config.json")))


def output_path(root, operation):
    folder = root / "artifacts"
    return (folder / "brochures" if operation in MAIN else folder) / f"{operation}.md"


def create_brochure(service, company, audience, sources, context, show, *, baseline=False, update=None):
    operation = "baseline" if baseline else f"{company.id}_{audience}"
    user = get_brochure_user_prompt(company, audience, context["text"], baseline)
    content, details = service.validated_writing(operation, company.id, audience, SYSTEM, user, context,
                                                lambda t: validate_brochure(t, context, sources, company.id), update)
    export(service.run, operation, content, details)
    if update is None:
        show(content)
    return content


def stream_brochure(service, company, audience, sources, context, update):
    return create_brochure(service, company, audience, sources, context, None, update=update)


def export(run, operation, content, details):
    dump_text(output_path(run.root, operation), content)
    dump_json(run.root / "metadata" / f"{operation}.json", dict(run_id=run.id, operation=operation, **details))
    run.log("validated", operation=operation, **details)


def compare(service, companies, sources, context, show):
    dimensions = read_json(service.run.root / "protocol.json")["dimensions"]
    user = comparison_prompt(companies, context["text"], dimensions)
    content, details = service.validated_writing("comparison", "AB", "both", SYSTEM, user, context,
                                                 lambda t: validate_comparison(t, context, sources, dimensions))
    export(service.run, "comparison", content, details)
    show(content)
    return content


def start_run(settings, mode, **provenance):
    run = Run.new(settings.output_dir)
    dump_json(run.root / "config.json", dict(settings.public(), run_id=run.id, mode=mode, format_version=2,
                                             selection_version=2, **provenance))
    dump_json(run.root / "protocol.json", PROTOCOL)
    run.log("started", mode=mode)
    return run


def run_workflow(settings, client, *, fetch=None, show=print, update=None, mode="live"):
    run = start_run(settings, mode)
    return generate(run, settings, client, fetch, show, update)


def failure_report(run, service, exc):
    failure = service.last_failure or {}
    if failure:
        summary = " ".join(str(value) for value in
                           (failure["operation"], f"attempt {failure['attempt']}", failure["error"],
                            f"HTTP {failure['http_status']}" if failure["http_status"] else "",
                            failure.get("provider_status", ""), safe_text(failure["provider_message"])) if value)
    else:
        summary = safe_text(exc, getattr(service.client, "api_key", None))
        last = run_events(run.root)[-1]
        if last["event"] == "selection_rejected":
            phase = "links" if last["phase"] == "selection" else "alternative"
            summary = f"{last['company']}_{phase} rejected selection: {summary}"
    run.log("workflow_failed", reason=summary, error_path=failure.get("error_path"))
    return RuntimeError(f"Run {run.id} incomplete ({summary}). Inspect {run.root}")


def generate(run, settings, client, fetch=None, show=print, update=None, checkpoint=None, stages=None, resume_attempts=None):
    service = ModelService(client, settings, run, resume_attempts)
    stages = stages or {}
    if fetch is None:
        def fetch(url, home, additional=False):
            return fetch_website_contents(url, home, settings.timeout, run.log, additional=additional)
    errors = {}
    try:
        for company in settings.companies:
            stage = stages.get(company.id, "collect")
            if stage == "reuse":
                continue
            if stage != "collect":
                resume_collection(run, company, service, fetch, stage)
                continue
            if checkpoint is not None and company.id == "A":
                page, candidates, raw = checkpoint
                finish_collection(run, company, page, candidates, raw, fetch,
                                  lambda c, plan: select_alternative(service, c, plan))
                continue
            fetch_page_and_all_relevant_links(run, company, fetch,
                                              lambda c, urls: select_relevant_links(service, c, urls),
                                              lambda c, plan: select_alternative(service, c, plan))
        collections = {cid: saved_sources(run.root, cid) for cid in "AB"}
        for operation in MAIN + ["comparison", "baseline"]:
            if stages.get(operation) == "reuse":
                continue
            cid = "A" if operation == "baseline" else operation[0]
            sources = sum(collections.values(), []) if operation == "comparison" else collections[cid]
            context = build_context(sources, settings.budget)
            run.log("context_budget", operation=operation, decisions=context["decisions"])
            company = settings.companies[0 if cid == "A" else 1]
            try:
                if operation == "comparison":
                    if {e["company_id"] for e in context["evidence"]} != {"A", "B"}:
                        raise ValueError("comparison budget must admit evidence for both companies")
                    compare(service, settings.companies, sources, context, show)
                elif operation == "B_candidates":
                    stream_brochure(service, company, "candidates", sources, context, update or show)
                else:
                    audience = "customers" if operation == "baseline" else operation.split("_")[1]
                    create_brochure(service, company, audience, sources, context, show, baseline=operation == "baseline")
            except ValueError as exc:
                errors[operation] = str(exc)
                run.log("output_rejected", operation=operation, reason=str(exc))
        if errors:
            raise ValueError(f"Unaccepted outputs: {errors}")
        replay(run.root)
        prepare_review(run.root)
        run.log("generation_complete", semantic_review="pending")
        return run.root
    except Exception as exc:
        raise failure_report(run, service, exc) from None


def run_events(root):
    return [json.loads(line) for line in read_text(root / "execution_log.jsonl").splitlines()]


def transient_failure(event):
    if event["success"] or event["status"] != "failed":
        return False
    if "http_status" in event:
        return event.get("retryable") is True and event["http_status"] in TRANSIENT
    # The old SDK log retained only the exception class. Allow an explicit diagnostic
    # for this legacy 5xx, but never assign a specific HTTP code to it.
    return event["operation"] == "A_links" and event.get("error") == "InternalServerError"


def interrupted_brochure(event):
    return (event["operation"] == "B_candidates" and not event["success"] and event["status"] == "partial"
            and event.get("parameters", {}).get("stream") is True
            and (event.get("provider_message") == "incomplete stream: missing finish event"
                 or event.get("error") in {"APIConnectionError", "APITimeoutError", "ReadError", "ReadTimeout",
                                           "ConnectionError", "RemoteProtocolError"}
                 or event.get("http_status") in TRANSIENT))


def call_history(root, config, events):
    """Check physical attempts, their saved inputs and the reason for each repeat."""
    groups, pending, starts = {}, {}, {}
    allowed = set(MAIN + ["baseline", "comparison", "A_links", "B_links", "A_alternative", "B_alternative"])
    current = None
    configured_limit = config.get("provider_retries", 0)
    authorized = {}
    for e in events:
        if e["event"] in {"continued_after_links", "workflow_resumed"}:
            configured_limit = e["provider_retries"]
            if not 0 <= configured_limit <= 3:
                raise ValueError("invalid continuation retry limit")
            if e["event"] == "workflow_resumed":
                if pending or starts or e["run_id"] != root.name:
                    raise ValueError("unresolved calls at resumption")
                authorized = dict(e["resume_attempts"])
                current = None
        if e["event"] not in ("retry", "llm", "llm_started"):
            continue
        op, attempt = e["operation"], e["attempt"]
        if op not in allowed or type(attempt) is not int or e["run_id"] != root.name:
            raise ValueError("invalid call identity")
        key = attempt_key(op, attempt)
        if e["event"] == "retry":
            if key in pending:
                raise ValueError("duplicate retry")
            pending[key] = e
            continue
        if e["event"] == "llm_started":
            if key in starts:
                raise ValueError("duplicate call start")
            starts[key] = e
            continue
        if op != current:
            if op in groups and (op not in authorized or pending.get(key, {}).get("kind") != "stage_resume"):
                raise ValueError("interleaved model operations")
            current = op
            groups.setdefault(op, [])
            repeats = 0
            limit = configured_limit
        group = groups[op]
        if attempt != len(group)+1 or e["model"] != config["model"]:
            raise ValueError("call sequence or model mismatch")
        error_path = f"responses/{key}_error.json"
        output = f"responses/{key}.txt" if e["success"] or e["status"] == "partial" else error_path
        if (e["input_path"] != f"prompts/{key}.json" or e["context_path"] != f"contexts/{key}.json"
                or e["output_path"] != output or not (root / output).is_file()):
            raise ValueError("call provenance mismatch")
        if not e["success"]:
            artifact = read_json(root / error_path)
            if any(e.get(k) != value for k, value in artifact.items()) or artifact.get("error") != e["error"]:
                raise ValueError("error record mismatch")
        if "parameters" in e:
            start = starts.pop(key, {})
            if not start or any(e.get(k) != v for k, v in start.items() if k not in {"at", "event"}):
                raise ValueError("missing or inconsistent call start")
            parameters = dict(model=config["model"], stream=op == "B_candidates", timeout_s=config["timeout"])
            if op.endswith(("_links", "_alternative")):
                response_format = selection_args(config).get("response_format")
                if response_format is not None:
                    parameters["response_format"] = response_format
            if e["parameters"] != parameters:
                raise ValueError("call parameters differ from run configuration")
        if group:
            retry = pending.pop(key, {})
            previous = group[-1]
            kind = retry.get("kind", "validation")
            if not retry or not retry.get("reason"):
                raise ValueError("missing reason for repeat")
            if kind == "provider":
                repeats += 1
                if (not transient_failure(previous) or previous.get("http_status") not in TRANSIENT
                        or retry["reason"] != f"HTTP {previous['http_status']}" or repeats > limit
                        or retry.get("retry_limit") != limit or retry.get("delay_s") != min(2 ** (repeats-1), 4)):
                    raise ValueError("unjustified provider retry")
            elif kind == "saved_input":
                if op != "A_links" or previous["success"] or not transient_failure(previous):
                    raise ValueError("unjustified diagnostic")
                repeats, limit = 0, retry["retry_limit"]
                if not 0 <= limit <= 3:
                    raise ValueError("invalid diagnostic retry limit")
            elif kind == "stage_resume":
                grant = authorized.pop(op, {})
                if (grant.get("attempt") != attempt or grant.get("reason") != retry["reason"]
                        or grant.get("had_sample") != any(p["success"] for p in group)
                        or retry.get("delay_s") != 0 or retry.get("retry_limit") != configured_limit
                        or (transient_failure(previous) and previous.get("http_status") and retry["reason"] != f"HTTP {previous['http_status']}")
                        or (interrupted_brochure(previous) and (not grant.get("partial_stream")
                                                                or retry["reason"] != previous["provider_message"]))
                        or not (transient_failure(previous) or interrupted_brochure(previous) or
                                (previous["success"] and op in MAIN + ["comparison", "baseline"]))):
                    raise ValueError("unjustified stage resume")
                repeats, limit = 0, configured_limit
            elif (kind == "validation" and previous["success"] and op in MAIN + ["comparison", "baseline"]
                  and sum(p["success"] for p in group) == 1):
                repeats = 0
            else:
                raise ValueError("unjustified repeat")
            if read_json(root / e["context_path"]) != read_json(root / previous["context_path"]):
                raise ValueError("repeat inputs changed")
            # Reconstruct revised writing prompts per attempt below. Transport retries stay identical.
            revised_writing = e.get("writing_version") == 2 and op in MAIN + ["comparison", "baseline"]
            if kind == "provider" or not revised_writing:
                if read_json(root / e["input_path"]) != read_json(root / previous["input_path"]):
                    raise ValueError("repeat inputs changed")
        group.append(e)
    if starts or pending:
        raise ValueError("unresolved model call or retry; inspect the log before proceeding")
    return groups


def check_source_records(company, sources, links):
    if len(sources) != len(links) + 1:
        raise ValueError("selection/source count mismatch")
    for i, s in enumerate(sources, 1):
        normalize_url(s["url"], company.url)
        timestamp = datetime.fromisoformat(s["retrieved_at"].replace("Z", "+00:00"))
        if (s["source_id"] != f"{company.id}{i}" or s["company_id"] != company.id or
                s["status"] not in ("ok", "empty", "failed") or timestamp.utcoffset() is None or
                bool(s["text"].strip()) != (s["status"] == "ok") or
                (i > 1 and s["requested_url"] != links[i-2]["url"])):
            raise ValueError("invalid source record")


def collection_stage(root, config, company, groups, order):
    name = f"{company.id}_links"
    order.append(name)
    if name not in groups:
        if any((root / "data").glob(f"{company.id}_*.json")):
            raise ValueError(f"untracked collection for {company.id}")
        return "collect"
    _, ctx, _ = link_inputs(root, config, company)
    candidates = ctx["candidates"]
    last = groups[name][-1]
    sources = saved_sources(root, company.id)
    if not last["success"]:
        check_source_records(company, sources, [])
        if (root / "data" / f"{company.id}_selection.json").exists():
            raise ValueError("selection exists after failed request")
        return "select"
    _, links = checked_selection(root, last, candidates, company)
    if len(sources) == 1 and links:
        check_source_records(company, sources, [])
        return "fetch_selected"
    primary = sources[:1+len(links)]
    check_source_records(company, primary, links)
    plan = alternative_plan(company, primary, candidates) if config.get("format_version") == 2 else None
    if plan and plan["remaining"] and plan["candidates"]:
        name = f"{company.id}_alternative"
        order.append(name)
        if name in groups:
            user, context = alternative_messages(company, plan)
            if read_json(root / "contexts" / f"{name}.json") != context:
                raise ValueError("alternative candidate context mismatch")
            check_request(root, name, config, user=user, **selection_args(config))
        if name not in groups or not groups[name][-1]["success"]:
            if len(sources) != len(primary) or (root / "data" / f"{name}_selection.json").exists():
                raise ValueError("unexpected alternative selection or sources")
            return "select_alternative"
        raw = read_text(root / groups[name][-1]["output_path"])
        extra = validate_selection(raw, plan["candidates"], company.url)
        if len(extra) > plan["remaining"] or read_json(root / "data" / f"{name}_selection.json") != dict(
                raw=raw, links=extra, valid=True, reason=""):
            raise ValueError("alternative selection mismatch")
        links = links + extra
    check_source_records(company, sources, links)
    return "reuse"


def writing_checkpoint(root, config, companies, collections, operation, group, events):
    """Revalidate every received sample. Only a matching exported artifact completes a stage."""
    company = companies[1 if operation.startswith("B_") else 0]
    sources = sum(collections.values(), []) if operation == "comparison" else collections[company.id]
    ctx = build_context(sources, config["budget"])
    if ctx != read_json(root / "contexts" / f"{operation}.json"):
        raise ValueError("saved context differs from source reconstruction")
    system = SYSTEM if config.get("format_version") == 2 else LEGACY_SYSTEM
    result, rejection = None, None
    for call in group:
        version = call.get("writing_version", 1)
        if version not in (1, 2):
            raise ValueError("unknown writing prompt version")
        if operation == "comparison":
            user = comparison_prompt(companies, ctx["text"], PROTOCOL["dimensions"], version=version)
        else:
            aud = "customers" if operation == "baseline" else operation.split("_")[1]
            user = get_brochure_user_prompt(company, aud, ctx["text"], operation == "baseline", version=version)
            if version == 2:
                user = length_feedback(rejection) + user
        check_request(root, attempt_key(operation, call["attempt"]), config, system, user)
        if not call["success"]:
            continue
        raw = read_text(root / call["output_path"])
        try:
            if operation == "comparison":
                result = validate_comparison(raw, ctx, sources, PROTOCOL["dimensions"], grouped=version == 2)
            else:
                result = validate_brochure(raw, ctx, sources, company.id)
        except ValueError as exc:
            rejection = str(exc)
            repeated = call != group[-1]
            required_event = "retry" if repeated else "validation_failed"
            if not any(e["event"] == required_event and e.get("operation") == operation
                       and e.get("reason") == rejection and e["attempt"] == call["attempt"] + int(repeated)
                       for e in events):
                raise ValueError("missing reason for rejected output") from exc
        else:
            if call != group[-1]:
                raise ValueError("repeat after a valid writing response")
            if call["attempt"] > 1:
                result["accepted_attempt"] = call["attempt"]
            if raw != read_text(output_path(root, operation)):
                raise ValueError("artifact differs from accepted raw response")
            if read_json(root / "metadata" / f"{operation}.json") != dict(run_id=root.name, operation=operation, **result):
                raise ValueError("metadata mismatch")
    # Revalidate the last unedited legacy comparison under the explicitly expanded citation syntax.
    if (operation == "comparison" and result is None and group[-1]["success"] and version == 1
            and rejection == "unknown, malformed or out-of-context citation"):
        try:
            reviewed = validate_comparison(raw, ctx, sources, PROTOCOL["dimensions"])
        except ValueError:
            pass
        else:
            if call["attempt"] > 1:
                reviewed["accepted_attempt"] = call["attempt"]
            artifact, metadata = output_path(root, operation), root / "metadata/comparison.json"
            recorded = any(e["event"] == "saved_response_revalidated" and e.get("output_path") == call["output_path"]
                           for e in events)
            if ((artifact.exists() and (not recorded or read_text(artifact) != raw))
                    or (metadata.exists() and (not recorded or read_json(metadata) !=
                                               dict(run_id=root.name, operation=operation, **reviewed)))):
                raise ValueError("revalidated comparison provenance mismatch")
            return reviewed, None if artifact.exists() and metadata.exists() else "revalidate_saved"
    if result is None and (output_path(root, operation).exists() or (root / "metadata" / f"{operation}.json").exists()):
        raise ValueError(f"unverified export for {operation}")
    return result, rejection


def audit_stages(root, config, events):
    if read_json(root / "protocol.json") != PROTOCOL or config["run_id"] != root.name:
        raise ValueError("run identity or preregistration mismatch")
    companies = tuple(Company(**c) for c in config["companies"])
    groups = call_history(root, config, events)
    order, stages, repeats, results, collections = [], {}, {}, {}, {}
    for company in companies:
        stage = collection_stage(root, config, company, groups, order)
        stages[company.id] = stage
        if stage == "reuse":
            collections[company.id] = saved_sources(root, company.id)
        elif any(op.startswith("B_") for op in groups) and company.id == "A":
            raise ValueError("company B started with incomplete A collection")

    for op in MAIN + ["comparison", "baseline"]:
        order.append(op)
        if op not in groups:
            if output_path(root, op).exists() or (root / "metadata" / f"{op}.json").exists():
                raise ValueError(f"untracked export for {op}")
            stages[op] = "generate"
            continue
        if len(collections) != len(companies):
            raise ValueError("writing started with incomplete collections")
        result, rejection = writing_checkpoint(root, config, companies, collections, op, groups[op], events)
        if result is not None:
            results[op] = result
            stages[op] = "revalidate_saved" if rejection == "revalidate_saved" else "reuse"
        else:
            stages[op] = "resume"
            if groups[op][-1]["success"]:
                repeats[op] = dict(reason=rejection)
            elif length_feedback(rejection):
                repeats[op] = dict(length_error=rejection)
    if list(groups) != order[:len(groups)]:
        raise ValueError("incomplete or unexpected model call history")
    for op, group in groups.items():
        last = group[-1]
        if not last["success"]:
            repeat = repeats.setdefault(op, {})
            if interrupted_brochure(last):
                repeat.update(reason=last["provider_message"], partial_stream=True)
            elif transient_failure(last):
                repeat.update(reason=f"HTTP {last['http_status']}" if last.get("http_status") else last["error"])
            else:
                raise ValueError(f"{op} stopped with a non-retryable or partial response")
        if op in repeats:
            repeats[op].update(attempt=last["attempt"]+1, had_sample=any(c["success"] for c in group))
    return stages, repeats, results


def replay(root):
    """Rebuild and verify all saved stages without constructing a provider client."""
    root = Path(root)
    stages, _, results = audit_stages(root, read_json(root / "config.json"), run_events(root))
    if any(stage != "reuse" for stage in stages.values()):
        raise ValueError("incomplete model call history")
    return results


def check_request(root, operation, config, system, user, response_format=None):
    expected = dict(model=config["model"], stream=operation.split(".")[0] == "B_candidates",
                    messages=[dict(role="system", content=system), dict(role="user", content=user)])
    if response_format is not None:
        expected["response_format"] = response_format
    request = read_json(root / "prompts" / f"{operation}.json")
    if request != expected:
        raise ValueError(f"saved request mismatch: {operation}")
    return request


def link_inputs(root, config, company):
    name = f"{company.id}_links"
    candidates = read_json(root / "data" / f"{company.id}_candidates.json")
    destinations = read_json(root / "data" / f"{company.id}_destinations.json")
    if list(destinations) != candidates or any(
            normalize_url(url, company.url) != candidate or forbidden(candidate, company.url)
            for candidate, url in destinations.items()):
        raise ValueError("normalized candidates differ from their transport URLs")
    context = read_json(root / "contexts" / f"{name}.json")
    if context != {"text": json.dumps(candidates, ensure_ascii=False, indent=2), "candidates": candidates}:
        raise ValueError("candidate context mismatch")
    request = check_request(root, name, config, user=link_prompt(company, context["text"]), **selection_args(config))
    return request, context, destinations


@contextmanager
def recovery_lock(root):
    lock = root / ".links-recovery.lock"
    try:
        lock.touch(exist_ok=False)
    except FileExistsError:
        raise RuntimeError(f"Check for an active recovery in {root} before removing a stale {lock.name}") from None
    try:
        yield
    finally:
        lock.unlink()


def check_saved_settings(root, settings):
    config = read_json(root / "config.json")
    if (config["run_id"] != root.name or config.get("format_version") != 2
            or read_json(root / "protocol.json") != PROTOCOL
            or config["companies"] != [asdict(c) for c in settings.companies]
            or config["base_url"].rstrip("/") != settings.base_url.rstrip("/")
            or any(config[k] != getattr(settings, k) for k in ("model", "budget", "timeout"))):
        raise ValueError("saved run identity, protocol or provider configuration differs")
    return config


def saved_checkpoint(root, settings):
    config = check_saved_settings(root, settings)
    events = run_events(root)
    groups = call_history(root, config, events)
    if list(groups) != ["A_links"] or any(e["event"] == "continued_after_links" for e in events):
        raise ValueError("recovery requires a run stopped at A_links")
    if events[-1]["event"] not in {"workflow_failed", "links_validated", "selection_rejected"}:
        raise ValueError("run has no recorded stop at A_links")
    company = settings.companies[0]
    request, context, destinations = link_inputs(root, config, company)
    sources = saved_sources(root, "A")
    if len(sources) != 1 or sources[0]["source_id"] != "A1" or sources[0]["company_id"] != "A":
        raise ValueError("expected a single saved A homepage")
    home = sources[0]
    normalize_url(home["url"], company.url)
    if home["status"] != "ok" or not home["text"].strip():
        raise ValueError("saved homepage is unusable")
    return groups["A_links"][-1], request, context, saved_page(home, destinations)


def saved_page(home, destinations):
    return Page(home["url"], home["status"], home["title"], home["text"],
                list(destinations.values()), home["retrieved_at"], home["error"])


def resume_collection(run, company, service, fetch, stage):
    sources = saved_sources(run.root, company.id)
    destinations = read_json(run.root / "data" / f"{company.id}_destinations.json")
    candidates = list(destinations)
    page = saved_page(sources[0], destinations)
    if stage == "select_alternative":
        plan = alternative_plan(company, sources, candidates)
        run.log("alternative_decision", company=company.id, reason=plan["reason"], slots=plan["remaining"],
                decision="Use saved primary sources and request the outstanding alternative selection")
        raw = select_alternative(service, company, plan)
        collect_selected(run, company, page, plan["candidates"], raw, fetch, existing=sources)
        return
    if stage == "select":
        raw = select_relevant_links(service, company, candidates)
    elif stage == "fetch_selected":
        raw = read_json(run.root / "data" / f"{company.id}_selection.json")["raw"]
    else:
        raise ValueError(f"unknown collection stage {stage}")
    finish_collection(run, company, page, candidates, raw, fetch,
                      lambda c, plan: select_alternative(service, c, plan))


def resume_workflow(root, settings, *, inspect=False, make_client=client_for, **generation):
    """Verify the entire checkpoint before creating a client or appending to the run."""
    root = Path(root).resolve()
    with nullcontext() if inspect else recovery_lock(root):
        config = check_saved_settings(root, settings)
        events = run_events(root)
        last = events[-1]
        local_export = (last["event"] == "saved_response_revalidated" or
                        (last["event"] == "validated" and last.get("operation") == "comparison"
                         and len(events) > 1 and events[-2]["event"] == "saved_response_revalidated"))
        if last["event"] not in {"workflow_failed", "links_validated", "generation_complete"} and not local_export:
            raise ValueError("no recorded workflow stop; inspect the log before resuming")
        stages, repeats, results = audit_stages(root, config, events)
        if inspect:
            return dict(run_id=root.name, model=config["model"], stages=stages, resume_attempts=repeats,
                        provider_retries=settings.provider_retries)
        needs_generation = any(stage not in {"reuse", "revalidate_saved"} for stage in stages.values())
        client = make_client(settings) if needs_generation else None
        if stages["comparison"] == "revalidate_saved":
            run = Run(root)
            details = results["comparison"]
            key = attempt_key("comparison", details.get("accepted_attempt", 1))
            path = f"responses/{key}.txt"
            run.log("saved_response_revalidated", operation="comparison", output_path=path,
                    reason="Validated each comma-separated citation against its context and table cell")
            export(run, "comparison", read_text(root / path), details)
            stages["comparison"] = "reuse"
        if all(stage == "reuse" for stage in stages.values()):
            if events[-1]["event"] != "generation_complete":
                prepare_review(root)
                Run(root).log("generation_complete", semantic_review="pending")
            return root
        run = Run(root)
        run.log("workflow_resumed", stages=stages, resume_attempts=repeats, provider_retries=settings.provider_retries)
        return generate(run, settings, client, stages=stages, resume_attempts=repeats, **generation)


def saved_links_step(root, settings, *, inspect=False, continue_run=False, make_client=client_for, **generation):
    """Continue a validated first selection; route a later stopped continuation through the stage audit."""
    root = Path(root).resolve()
    if continue_run and not inspect:
        events = run_events(root)
        if events[-1]["event"] == "workflow_failed" and any(
                e["event"] in {"continued_after_links", "workflow_resumed"} for e in events):
            return resume_workflow(root, settings, make_client=make_client, **generation)
    with nullcontext() if inspect else recovery_lock(root):
        last, request, context, page = saved_checkpoint(root, settings)
        if inspect:
            return dict(run_id=root.name, operation="A_links", model=request["model"], base_url=settings.base_url,
                        parameters=list(request), stream=request["stream"], candidates=len(context["candidates"]),
                        message_chars=sum(len(m["content"]) for m in request["messages"]), attempt=last["attempt"],
                        http_status=last.get("http_status"), error=last.get("error"), timeout_s=settings.timeout)
        if continue_run:
            if not last["success"]:
                raise ValueError("continuation requires a validated A_links result")
            raw, _ = checked_selection(root, last, context["candidates"], settings.companies[0])
            client = make_client(settings)
            run = Run(root)
            run.log("continued_after_links", accepted_attempt=last["attempt"], provider_retries=settings.provider_retries)
            return generate(run, settings, client, checkpoint=(page, context["candidates"], raw), **generation)
        return recover_links(Run(root), settings, make_client, last, request, context)


def checked_selection(root, last, candidates, company):
    raw = read_text(root / last["output_path"])
    links = validate_selection(raw, candidates, company.url)
    if read_json(root / "data" / f"{company.id}_selection.json") != dict(raw=raw, valid=True, reason="", links=links):
        raise ValueError("saved selection mismatch")
    return raw, links


def recover_links(run, settings, make_client, last, request, context):
    root, company, candidates = run.root, settings.companies[0], context["candidates"]
    selection_path = root / "data/A_selection.json"
    if last["success"]:
        checked_selection(root, last, candidates, company)
        return selection_path
    if selection_path.exists() or not transient_failure(last):
        raise ValueError("saved A_links result is ineligible for a transient 5xx retry")
    service = ModelService(make_client(settings), settings, run)
    attempt = last["attempt"]+1
    run.log("retry", operation="A_links", kind="saved_input", attempt=attempt, reason="Explicit saved-input diagnostic",
            delay_s=0, retry_limit=settings.provider_retries)
    try:
        system, user = request["messages"]
        raw = service.call("A_links", "A", "both", system["content"], user["content"], context, attempt=attempt,
                           response_format=request.get("response_format"))
        links = save_selection(run, company, candidates, raw)
    except Exception as exc:
        raise failure_report(run, service, exc) from None
    run.log("links_validated", operation="A_links", count=len(links))
    return selection_path


def reselect_links(source, settings, *, inspect=False, make_client=client_for):
    """Try the current selection contract on a saved rejection, in a separate run."""
    source = Path(source).resolve()
    last, _, context, _ = saved_checkpoint(source, settings)
    rejection = read_json(source / "data/A_selection.json")
    if (not last["success"] or rejection.get("valid") is not False or not rejection.get("reason")
            or rejection.get("raw") != read_text(source / last["output_path"])):
        raise ValueError("reselection requires a saved, rejected A_links response")
    company = settings.companies[0]
    if inspect:
        return dict(source_run=source.name, model=settings.model, candidates=len(context["candidates"]),
                    user=link_prompt(company, context["text"]),
                    **selection_args(dict(settings.public(), selection_version=2)))
    client = make_client(settings)
    run = start_run(settings, read_json(source / "config.json")["mode"], source_run_id=source.name)
    (run.root / "data").mkdir()
    for name in ("A_sources.json", "A_candidates.json", "A_destinations.json"):
        copyfile(source / "data" / name, run.root / "data" / name)
    run.log("selection_inputs_reused", source_run_id=source.name, previous_attempt=last["attempt"],
            rejection_reason=rejection["reason"])
    service = ModelService(client, settings, run)
    try:
        raw = select_relevant_links(service, company, context["candidates"])
        links = save_selection(run, company, context["candidates"], raw)
    except Exception as exc:
        raise failure_report(run, service, exc) from None
    run.log("links_validated", operation="A_links", count=len(links))
    return run.root


def preflight(settings):
    """A separate website diagnostic; never adds pages to a generation run."""
    run = Run.new(settings.output_dir / "preflight")
    results = []
    for c in settings.companies:
        page = fetch_website_contents(c.url, c.url, settings.timeout, run.log)
        candidates = candidate_urls(fetch_website_links(page), page.url, c.url)
        results.append(dict(company=c.name, url=c.url, final_url=page.url, title=page.title, status=page.status,
                            retrieved_at=page.retrieved_at, chars=len(page.text), sample=page.text[:800],
                            candidates=candidates, error=page.error))
    dump_json(run.root / "sites.json", results)
    hosts = []
    for url in [c.url for c in settings.companies] + [settings.base_url]:
        route = urlsplit(url)
        port = route.port or (443 if route.scheme == "https" else 80)
        entry = {"host": route.hostname, "port": port}
        try:
            socket.getaddrinfo(route.hostname, port, type=socket.SOCK_STREAM)
            entry["dns"] = "resolved"
            with socket.create_connection((route.hostname, port), timeout=3):
                entry["tcp"] = "connected"
        except OSError as exc:
            entry.update(error=type(exc).__name__, os_error=exc.errno)
            if getattr(exc, "winerror", None) is not None:
                entry["winerror"] = exc.winerror
        hosts.append(entry)
    provider = {"base_url": settings.base_url, "model": settings.model, "checked": False}
    if urlsplit(settings.base_url).hostname in {"127.0.0.1", "localhost", "::1"}:
        provider["checked"] = True
        try:
            response = requests.get(settings.base_url.rstrip("/") + "/models", timeout=5, allow_redirects=False)
            response.raise_for_status()
            provider["models"] = [m["id"] for m in response.json()["data"]]
            provider["available"] = settings.model in provider["models"]
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            provider.update(available=False, error=type(exc).__name__)
    dump_json(run.root / "connectivity.json", {"sockets": hosts, "provider": provider})
    return run.root, results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    sub.add_parser("live").add_argument("--after-links", type=Path, help="Continue a validated A_links checkpoint")
    diagnostic = sub.add_parser("links-only", help="Run only A_links using verified saved inputs")
    diagnostic.add_argument("run", type=Path)
    diagnostic.add_argument("--inspect", action="store_true", help="Verify saved inputs offline without writing")
    revised = sub.add_parser("reselect-links", help="Run only the revised A_links on a saved rejection in a new run")
    revised.add_argument("run", type=Path)
    revised.add_argument("--inspect", action="store_true", help="Preview the revised selection inputs offline")
    resume = sub.add_parser("resume", help="Continue the same run from verified collection and writing stages")
    resume.add_argument("run", type=Path)
    resume.add_argument("--inspect", action="store_true", help="Show verified stages and next attempts offline")
    for name in ("replay", "review"):
        sub.add_parser(name).add_argument("run", type=Path)
    args = parser.parse_args()
    if args.command == "replay":
        print(json.dumps(replay(args.run), ensure_ascii=False, indent=2))
    elif args.command == "review":
        replay(args.run)
        print("Published reviewed claims and paired prompt evaluation:", publish_review(args.run))
    elif args.command == "preflight":
        path, sites = preflight(Settings.load())
        print(path, [(s["company"], s["status"]) for s in sites])
        diagnostics = read_json(path / "connectivity.json")
        print(json.dumps(diagnostics, indent=2))
        if any(s["status"] != "ok" for s in sites) or diagnostics["provider"].get("available") is False:
            raise SystemExit(1)
    elif args.command == "links-only":
        result = saved_links_step(args.run, Settings.load(), inspect=args.inspect)
        print(json.dumps(result, indent=2) if args.inspect else f"A_links validated: {result}")
    elif args.command == "reselect-links":
        result = reselect_links(args.run, Settings.load(), inspect=args.inspect)
        if args.inspect:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(read_json(result / "data/A_selection.json")["links"], indent=2, ensure_ascii=False))
            print(f"Validated A_links in {result}")
    elif args.command == "resume":
        result = resume_workflow(args.run, Settings.load(), inspect=args.inspect)
        print(json.dumps(result, indent=2) if args.inspect else result)
    elif args.after_links:
        print(saved_links_step(args.after_links, Settings.load(), continue_run=True))
    else:
        settings = Settings.load()
        print(run_workflow(settings, client_for(settings)))


if __name__ == "__main__":
    main()

