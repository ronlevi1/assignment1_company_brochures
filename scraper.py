"""Course requests + BeautifulSoup scraper. Manual redirects allow validation before the next GET."""
from dataclasses import dataclass, field
from time import monotonic
from urllib.parse import urljoin

import requests

from storage import utc_now
from url_utils import clean_url, normalize_url, forbidden


@dataclass
class Page:
    url: str
    status: str
    title: str = ""
    text: str = ""
    hrefs: list = field(default_factory=list)
    retrieved_at: str = field(default_factory=utc_now)
    error: str = ""


def parse_page(url, content):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(content, "html.parser")
    hrefs = [tag["href"] for tag in soup.select("a[href]")]
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup.select("script,style,noscript,template,svg,nav,footer"):
        if tag.parent is not None:
            tag.decompose()
    body = soup.find("main") or soup.body or soup.find("article")
    text = body.get_text("\n", strip=True) if body else ""
    return Page(url, "ok" if text else "empty", title, text, hrefs)


def fetch_website_links(page):
    return page.hrefs


def fetch_website_contents(url, home, timeout, log, *, additional=False, get=requests.get):
    current = url
    seen = set()
    try:
        for _ in range(7):
            current = clean_url(current, home, fold_www=False)
            normalize_url(current, home)
            if additional and forbidden(current, home):
                raise ValueError("forbidden destination")
            if current in seen:
                raise ValueError("redirect loop")
            seen.add(current)
            start = monotonic()
            status = None
            try:
                response = get(current, timeout=timeout, allow_redirects=False,
                               headers={"User-Agent": "Mozilla/5.0 (compatible; AcademicBrochure/1.0)"})
                status = response.status_code
                response.raise_for_status()
            finally:
                log("http", url=current, status=status, success=status is not None and 200 <= status < 400,
                    duration_s=monotonic()-start)
            if 300 <= status < 400:
                if not response.headers.get("Location"):
                    raise ValueError("redirect missing destination")
                current = urljoin(current, response.headers["Location"])
                continue
            if "html" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("response is not HTML")
            page = parse_page(current, response.content)
            if page.status == "empty":
                log("source_empty", url=current)
            return page
        raise ValueError("redirect limit exceeded")
    except (OSError, requests.RequestException, ValueError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        log("source_failed", url=url, reason=reason)
        return Page(url, "failed", error=reason)

