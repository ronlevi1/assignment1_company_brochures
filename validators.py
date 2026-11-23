import re

from prompt_builder import MISSING

REFERENCE_HEADER = "## מקורות"
CITE = re.compile(r"\[([^\[\]\n]+)\]")
HEBREW = re.compile(r"[א-ת]")


def body_and_refs(text):
    lines = text.splitlines()
    indices = [i for i, line in enumerate(lines) if line.strip() == REFERENCE_HEADER]
    if len(indices) != 1:
        raise ValueError("one final ## מקורות section required")
    i = indices[0]
    return "\n".join(lines[:i]).strip(), [line.strip() for line in lines[i+1:] if line.strip()]


def ids_in(text, allowed, *, grouped=False):
    matches = CITE.findall(text)
    ids = {part for group in matches for part in re.split(r"[ \t]*,[ \t]*", group)} if grouped else set(matches)
    if ids - allowed or text.count("[") != len(matches) or text.count("]") != len(matches):
        raise ValueError("unknown, malformed or out-of-context citation")
    return ids


def allowed_sources(context, sources, company_ids):
    index = {s["source_id"]: s for s in sources}
    allowed = {}
    for entry in context["evidence"]:
        sid = entry["source_id"]
        source = index.get(sid, {})
        if (source.get("status") != "ok" or source.get("company_id") not in company_ids
            or not re.fullmatch(r"[AB][1-4]", sid) or sid[0] != source["company_id"]
            or any(source[k] != entry[k] for k in ("company_id", "title", "url"))
            or not entry["text"] or not source["text"].startswith(entry["text"])):
            raise ValueError("inconsistent evidence")
        allowed[sid] = source["url"]
    return allowed


def hebrew_prose(text):
    """A script check, not an assessment of language quality or term accuracy."""
    words = re.findall(r"[^\W\d_]+", CITE.sub("", text), flags=re.UNICODE)
    hebrew = sum(bool(HEBREW.search(word)) for word in words)
    if not words or hebrew * 3 < len(words) * 2:
        raise ValueError("Write the prose in Hebrew; names and technical terms may retain their spelling")


def validate_brochure(text, context, sources, company_id):
    body, lines = body_and_refs(text)
    count = len(body.split())
    if not 200 <= count <= 300:
        raise ValueError(f"word count {count} outside 200–300")
    hebrew_prose(body)
    allowed = allowed_sources(context, sources, {company_id})
    cited = ids_in(body, set(allowed))
    expected = {f"- [{sid}] {allowed[sid]}" for sid in cited}
    if not cited or len(lines) != len(expected) or set(lines) != expected:
        raise ValueError("source list must match body citations and saved URLs exactly")
    return dict(word_count=count, cited=sorted(cited))


def validate_comparison(text, context, sources, dimensions, *, grouped=True):
    allowed = allowed_sources(context, sources, {"A", "B"})
    ids_in(text, set(allowed), grouped=grouped)
    hebrew_prose(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 7 or any("|" in line for line in lines[6:]):
        raise ValueError("four rows and a concluding paragraph required")
    rows = [line.strip("|").split("|") for line in lines[:6]]
    if any(len(row) != 4 for row in rows) or not all(re.fullmatch(r":?-{3,}:?", c.strip()) for c in rows[1]):
        raise ValueError("expected a four-column Markdown table")
    for dimension, row in zip(dimensions, rows[2:]):
        if row[0].strip() != dimension or not row[3].strip():
            raise ValueError("wrong dimension or absent difference")
        if row[3].strip() != MISSING and {sid[0] for sid in ids_in(row[3], set(allowed), grouped=grouped)} != {"A", "B"}:
            raise ValueError("difference requires evidence from both companies")
        for prefix, cell in zip("AB", row[1:3]):
            cited = ids_in(cell, {sid for sid in allowed if sid.startswith(prefix)}, grouped=grouped)
            if not cited and cell.strip() != MISSING:
                raise ValueError(f"unsupported company {prefix} cell")
    if not HEBREW.search(" ".join(lines[6:])):
        raise ValueError("missing interpretation")
    return dict(dimensions=dimensions)

