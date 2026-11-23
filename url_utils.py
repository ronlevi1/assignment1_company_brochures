"""Canonical identity folds one leading www and trailing slash; transport keeps the actual host."""
import posixpath
import re
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit


def clean_url(raw, base, *, fold_www=True):
    if not isinstance(raw, str) or not raw.strip() or re.search(r"[\x00-\x20\x7f\\]", raw.strip()):
        raise ValueError("empty or unsafe URL")
    parts = urlsplit(urljoin(base, raw.strip()))
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError("invalid web address")
    host = parts.hostname.lower().rstrip(".").encode("idna").decode("ascii")
    if fold_www:
        host = host.removeprefix("www.")
    if ":" in host:
        host = f"[{host}]"
    if parts.port is not None and parts.port != {"https": 443, "http": 80}[parts.scheme]:
        host += f":{parts.port}"
    path = parts.path or "/"
    if re.search(r"%(2f|5c|25)", path, re.I) or ".." in unquote(path).split("/"):
        raise ValueError("ambiguous path")
    if fold_www:
        path = "/" + posixpath.normpath(path).strip("/")
    return urlunsplit((parts.scheme, host, path, parts.query, ""))


def normalize_url(raw, home):
    value = clean_url(raw, home)
    if urlsplit(value).netloc != urlsplit(clean_url(home, home)).netloc:
        raise ValueError("external host or port")
    return value


def forbidden(url, home):
    p = urlsplit(normalize_url(url, home))
    page = unquote(p.path + "?" + p.query).casefold()
    homepage = urlsplit(clean_url(home, home)).path
    return (p.path == homepage or p.path == "/" or
            bool(re.search(r"(?:^|[/_.?=&-])(privacy|terms|tos|tcs|legal|תנאי|פרטיות)|מדיניות[-_]פרטיות", page)) or
            p.path.lower().rstrip("/").endswith(("/index.html", "/index.htm", "/index.php")))


def candidate_destinations(hrefs, base, home):
    """Map each candidate identity to the first actual linked destination."""
    result = {}
    for href in hrefs:
        try:
            if not href or not href.strip():
                continue
            absolute = clean_url(href, base, fold_www=False)
            url = normalize_url(absolute, home)
            if not forbidden(url, home) and not forbidden(url, base):
                result.setdefault(url, absolute)
        except (ValueError, UnicodeError):
            continue
    return result


def candidate_urls(hrefs, base, home):
    return list(candidate_destinations(hrefs, base, home))

