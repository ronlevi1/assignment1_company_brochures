"""URL rules and all-or-nothing validation for Day 5 link selection."""

import json
import posixpath
import re
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit


POLICY_PAGES = {
    "privacy", "privacy-policy", "privacy-notice", "data-policy", "dpa",
    "terms", "tos", "terms-of-service", "terms-of-use", "terms-and-conditions",
}


def normalize_url(homepage, href):
    """Return one eligible absolute URL, or None when the link is ineligible."""
    if not isinstance(href, str) or not href.strip():
        return None
    href = href.strip()
    if "\\" in href or any(ord(char) < 32 or char.isspace() for char in href):
        return None
    try:
        home = urlsplit(homepage)
        raw = urlsplit(href)
        if raw.scheme and (raw.scheme not in ("http", "https") or not raw.netloc):
            return None
        if href.startswith("//") and not raw.netloc:
            return None
        url = urlsplit(urljoin(homepage, href))
        host = (url.hostname or "").removeprefix("www.")
        if host != home.hostname.removeprefix("www.") or url.username is not None:
            return None
        defaults = {"http": 80, "https": 443}
        port = url.port if url.port != defaults[url.scheme] else None
        home_port = home.port if home.port != defaults[home.scheme] else None
        if port != home_port:
            return None
    except ValueError:
        return None

    path = posixpath.normpath(url.path or "/").rstrip("/")
    decoded = posixpath.normpath(unquote(path) or "/").strip("/").lower()
    if decoded == unquote(home.path).strip("/").lower() or decoded in {"index.html", "index.htm", "index.php"}:
        return None
    for segment in decoded.split("/"):
        slug = segment.split(".")[0].replace("_", "-")
        if slug in POLICY_PAGES:
            return None
    authority = home.hostname if port is None else f"{home.hostname}:{port}"
    return urlunsplit((url.scheme, authority, path or "/", url.query, ""))


def normalize_candidates(homepage, hrefs):
    """Keep the first occurrence of each eligible normalized URL."""
    candidates = []
    seen = set()
    for href in hrefs:
        url = normalize_url(homepage, href)
        if url is not None and url not in seen:
            candidates.append(url)
            seen.add(url)
    return candidates


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def validate_selection(raw_text, homepage, candidates):
    """Return all selected items in order, or raise ValueError before returning any."""
    if not isinstance(raw_text, str):
        raise ValueError("Missing response text.")
    data = json.loads(raw_text, object_pairs_hook=_unique_keys, parse_constant=_invalid_constant)
    if not isinstance(data, dict) or not isinstance(data.get("links"), list):
        raise ValueError("Expected an object with a links list.")
    items = data["links"]
    if len(items) > 3:
        raise ValueError("At most three links may be selected.")

    seen = set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Item {index} must be an object.")
        for field in ("type", "url", "reason"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"Item {index} needs a non-empty string for {field}.")
        url = normalize_url(homepage, item["url"])
        if url is None:
            raise ValueError(f"Item {index} is a forbidden URL.")
        if url in seen:
            raise ValueError(f"Item {index} duplicates a normalized URL.")
        if item["url"] != url or url not in candidates:
            raise ValueError(f"Item {index} does not match an exact candidate URL.")
        seen.add(url)
    return items


def validate_output(text, sources, brochure=True):
    """Check mechanical output requirements against the sources in this call."""
    sections = re.split(r"(?m)^## מקורות[ \t]*\r?$", text, maxsplit=1) if brochure else [text]
    body = sections[0]
    errors = []
    def citation_ids(section):
        ids = set()
        for group in re.findall(r"\[([^\]\n]+)\]", section):
            if not re.search(r"[A-Za-z]+\d+", group):
                continue
            for token in group.split(","):
                token = token.strip()
                if re.fullmatch(r"[A-Za-z]+[0-9]+", token):
                    ids.add(token)
                else:
                    errors.append("Malformed citation: " + group)
        return ids

    body_ids = citation_ids(body)
    cited = body_ids.union(citation_ids(sections[1]) if len(sections) == 2 else ())
    unknown = sorted(cited - sources.keys())
    if unknown:
        errors.append("Unknown source IDs: " + ", ".join(unknown))
    if not body_ids:
        errors.append("Missing inline citations")
    report = {"cited_ids": sorted(cited), "errors": errors}
    if brochure:
        count = len(body.split())
        report["word_count"] = count
        if not 200 <= count <= 300:
            errors.append("Word count outside 200-300")
        if len(sections) != 2:
            errors.append("Missing final sources heading")
        else:
            lines = {line.strip().removeprefix("- ") for line in sections[1].splitlines() if line.strip()}
            expected = {f"[{sid}] {sources[sid]}" for sid in body_ids if sid in sources}
            allowed = {f"[{sid}] {url}" for sid, url in sources.items()}
            if not expected <= lines <= allowed:
                errors.append("Source list differs from the cited IDs and URLs")
    else:
        # Validate the requested table separately from brochure length and references.
        lines = body.splitlines()
        tables = [i for i, line in enumerate(lines) if "|" in line and
                  re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*\|\s*:?-{3,}:?\s*\|\s*:?-{3,}:?\s*\|?\s*", line)]
        if len(tables) != 1 or tables[0] == 0:
            errors.append("Missing three-column comparison table")
        else:
            start = tables[0] + 1
            rows = []
            for line in lines[start:]:
                if "|" not in line:
                    break
                rows.append(line.strip().strip("|").split("|"))
            if len(rows) != 4 or any(len(row) != 3 for row in rows):
                errors.append("Expected four comparison rows with three columns")
            if not any(line.strip() for line in lines[start + len(rows):]):
                errors.append("Missing comparison conclusion")
    report["valid"] = not errors
    return report
