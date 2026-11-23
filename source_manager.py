import json

from scraper import fetch_website_links
from storage import dump_json
from url_utils import candidate_destinations, normalize_url, forbidden


def validate_selection(raw, candidates, home):
    def unique_object(pairs):
        obj = dict(pairs)
        if len(obj) != len(pairs):
            raise ValueError("duplicate JSON field")
        return obj

    def reject_constant(value):
        raise ValueError(f"invalid JSON constant {value}")

    if isinstance(raw, str) and raw.lstrip().startswith("```"):
        raise ValueError("expected bare JSON; received a Markdown code fence")
    value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    if not isinstance(value, dict) or not isinstance(value.get("links"), list):
        raise ValueError("expected object containing a links array")
    links = value["links"]
    if len(links) > 3:
        raise ValueError("more than three items")
    seen = set()
    for link in links:
        if not isinstance(link, dict) or not all(isinstance(link.get(k), str) and link[k].strip()
                                                for k in ("type", "url", "reason")):
            raise ValueError("type, url and reason must be nonempty strings")
        url = normalize_url(link["url"], home)
        if url in seen:
            raise ValueError("duplicate normalized URL")
        if forbidden(url, home) or link["url"] not in candidates or url != link["url"]:
            raise ValueError("forbidden or unlisted URL")
        seen.add(url)
    return links


def record(company, index, page):
    return dict(source_id=f"{company.id}{index}", company_id=company.id, url=page.url,
                title=page.title, text=page.text, retrieved_at=page.retrieved_at,
                status=page.status, error=page.error)


def save_selection(run, company, candidates, raw, phase="selection", slots=3):
    selection_path = run.root / "data" / f"{company.id}_{phase}.json"
    try:
        links = validate_selection(raw, candidates, company.url)
        if len(links) > slots:
            raise ValueError("selection exceeds remaining source slots")
    except ValueError as exc:
        dump_json(selection_path, dict(raw=raw, valid=False, reason=str(exc)))
        run.log("selection_rejected", company=company.id, phase=phase, reason=str(exc))
        raise
    dump_json(selection_path, dict(raw=raw, valid=True, reason="", links=links))
    return links


def collect_selected(run, company, homepage, candidates, raw, fetch, *, existing=None):
    prefix = run.root / "data" / company.id
    destinations = candidate_destinations(homepage.hrefs, homepage.url, company.url)
    sources = list(existing) if existing is not None else [record(company, 1, homepage)]
    phase = "alternative_selection" if existing is not None else "selection"
    dump_json(prefix.with_name(company.id + "_sources.json"), sources)
    links = save_selection(run, company, candidates, raw, phase, 4-len(sources))
    seen = {normalize_url(s["url"], company.url) for s in sources}
    for index, item in enumerate(links, len(sources)+1):
        page = fetch(destinations.get(item["url"], item["url"]), company.url, additional=True)
        identity = normalize_url(page.url, company.url)
        if page.status == "ok" and (identity in seen or forbidden(page.url, homepage.url)):
            page.status, page.text, page.error = "failed", "", "duplicate or forbidden final destination"
            run.log("source_failed", url=page.url, reason=page.error)
        seen.add(identity)
        source = record(company, index, page)
        source["requested_url"] = item["url"]
        sources.append(source)
        dump_json(prefix.with_name(company.id + "_sources.json"), sources)
        if page.status != "ok":
            run.log("evidence_gap", company=company.id, source_id=source["source_id"],
                    status=page.status, reason=page.error or "no readable text",
                    decision="Exclude from evidence; retain this occupied source slot.")
    return sources


def alternative_plan(company, sources, candidates):
    """Failed attempts consume page slots. A short collection can justify using a spare slot."""
    bad = [s["source_id"] for s in sources if s["status"] != "ok"]
    total = sum(len(s["text"].strip()) for s in sources if s["status"] == "ok")
    if not bad and total >= 1200:
        return None
    used = {normalize_url(s[key], company.url) for s in sources
            for key in ("url", "requested_url") if key in s}
    return dict(reason=f"Usable characters: {total}; unavailable source IDs: {bad}.",
                remaining=4-len(sources), candidates=[url for url in candidates if url not in used])


def fetch_page_and_all_relevant_links(run, company, fetch, select, select_alternative=None):
    page = fetch(company.url, company.url)
    dump_json(run.root / "data" / f"{company.id}_sources.json", [record(company, 1, page)])
    if page.status != "ok":
        raise ValueError(f"Homepage {company.id} is {page.status}; inspect and select a readable site")
    destinations = candidate_destinations(fetch_website_links(page), page.url, company.url)
    candidates = list(destinations)
    dump_json(run.root / "data" / f"{company.id}_destinations.json", destinations)
    dump_json(run.root / "data" / f"{company.id}_candidates.json", candidates)
    raw = select(company, candidates)
    return finish_collection(run, company, page, candidates, raw, fetch, select_alternative)


def finish_collection(run, company, page, candidates, raw, fetch, select_alternative):
    sources = collect_selected(run, company, page, candidates, raw, fetch)
    plan = alternative_plan(company, sources, candidates)
    if plan is not None:
        possible = bool(plan["remaining"] and plan["candidates"] and select_alternative)
        run.log("alternative_decision", company=company.id, reason=plan["reason"], slots=plan["remaining"],
                decision="Request another selection" if possible else "Continue with saved evidence and record gaps")
        if possible:
            raw = select_alternative(company, plan)
            sources = collect_selected(run, company, page, plan["candidates"], raw, fetch, existing=sources)
    return sources

