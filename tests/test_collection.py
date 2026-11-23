import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from config import Company
from scraper import Page, fetch_website_contents
from source_manager import collect_selected, fetch_page_and_all_relevant_links, validate_selection
from storage import Run, read_json
from url_utils import candidate_urls

HOME = "https://site.test/"
URL = HOME + "about"
ITEM = dict(type="about", url=URL, reason="team")
C = Company("A", "Fixture", HOME)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Run.new(Path(self.tmp.name))
        self.fetch = Mock(side_effect=AssertionError("unexpected selected-page GET"))

    def test_candidates(self):
        links = [None, "", "  ", "#x", "?utm=1", "/about/", "https://WWW.SITE.TEST:443/about#x", "tel:99",
                 "mailto:name@site.test", "javascript:go()", "ftp://site.test/file", "https://site.test.evil.test",
                 "//user@site.test/p", "//site.test:8000/p", "/privacy-policy", "/tErMs-of-use", "/%70rivacy",
                 "/index.html", "/legal/terms", "https://sub.site.test/jobs", "jobs", "/work?q=dev#roles"]
        self.assertEqual(candidate_urls(links, HOME, HOME), [URL, HOME+"jobs", HOME+"work?q=dev"])

    def test_atomic_rejections(self):
        invalid = ["{", "null", "[]", "{}", '{"links":{}}', '{"links":[],"links":[]}',
                   '{"links":[],"extra":NaN}']
        for bad in (dict(ITEM, url=HOME+"unknown"), dict(ITEM, url="https://outside.test/"),
                    dict(ITEM, url=HOME), dict(ITEM, url=HOME+"privacy"),
                    dict(ITEM, url=HOME+"terms-of-service"), ITEM, dict(ITEM, url=URL+"/#x"),
                    dict(ITEM, reason=" "), dict(ITEM, type=3), dict(ITEM, url=None),
                    dict(type="about", url=URL), {}):
            invalid.append(json.dumps({"links": [ITEM, bad]}))
        invalid.append(json.dumps({"links": [ITEM]*4}))
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                collect_selected(self.run, C, Page(HOME, "ok", text="home"), [URL], raw, self.fetch)
            self.fetch.assert_not_called()
            result = read_json(self.run.root/"data/A_selection.json")
            self.assertEqual(result["raw"], raw)
            self.assertFalse(result["valid"])
            self.assertTrue(result["reason"])

    def test_forbidden_even_if_candidate_file_is_bad(self):
        bad = HOME+"privacy"
        with self.assertRaises(ValueError):
            validate_selection(json.dumps({"links": [ITEM, dict(ITEM, url=bad)]}), [URL, bad], HOME)

    def test_empty_selection(self):
        sources = collect_selected(self.run, C, Page(HOME, "ok", text="home"), [], '{"links":[]}', self.fetch)
        self.assertEqual([s["source_id"] for s in sources], ["A1"])
        self.fetch.assert_not_called()

    def test_rejected_model_response_in_course_workflow(self):
        fetch = Mock(return_value=Page(HOME, "ok", "Fixture", "text", ["/about"]))
        with self.assertRaises(ValueError):
            fetch_page_and_all_relevant_links(self.run, C, fetch, lambda *_: '{"links":[{}]}')
        fetch.assert_called_once_with(HOME, HOME)
        self.assertEqual(read_json(self.run.root/"data/A_candidates.json"), [URL])

    def test_www_alias_uses_original_route_for_fetch(self):
        actual = "https://www.site.test/team/"
        fetch = Mock(side_effect=[Page(HOME, "ok", text="home", hrefs=[actual]), Page(actual, "ok", text="team")])
        canonical = HOME+"team"
        raw = json.dumps(dict(links=[dict(ITEM, url=canonical)]))
        docs = fetch_page_and_all_relevant_links(self.run, C, fetch, lambda *_: raw)
        self.assertEqual(read_json(self.run.root/"data/A_candidates.json"), [canonical])
        self.assertEqual(docs[1]["url"], actual)
        fetch.assert_called_with(actual, HOME, additional=True)

    def test_source_status_and_order(self):
        urls = [URL, HOME+"empty", HOME+"down"]
        pages = [Page(URL, "ok", "About", "X"*15000), Page(urls[1], "empty"), Page(urls[2], "failed", error="timeout")]
        raw = json.dumps({"links": [dict(ITEM, url=u) for u in urls]})
        company = Company("B", "Fixture", HOME)
        fetch = Mock(side_effect=pages)
        sources = collect_selected(self.run, company, Page(HOME, "ok", text="home"), urls, raw, fetch)
        self.assertEqual(sources, read_json(self.run.root/"data/B_sources.json"))
        self.assertEqual([s["source_id"] for s in sources], ["B1", "B2", "B3", "B4"])
        self.assertEqual([s["status"] for s in sources], ["ok", "ok", "empty", "failed"])
        self.assertTrue(all(s["retrieved_at"].endswith("Z") for s in sources))
        self.assertEqual(len(sources[1]["text"]), 15000)

    def test_duplicate_redirected_evidence(self):
        raw = json.dumps({"links": [ITEM]})
        sources = collect_selected(self.run, C, Page(HOME, "ok", text="home"), [URL], raw,
                                   Mock(return_value=Page(HOME, "ok", text="home")))
        self.assertEqual(sources[1]["status"], "failed")

    def test_redirect_checked_before_next_get(self):
        for destination in ["https://site.test.evil.test/path", HOME+"terms", HOME]:
            get = Mock(return_value=SimpleNamespace(status_code=302, headers={"Location": destination},
                                                    raise_for_status=lambda: None))
            self.assertEqual(fetch_website_contents(URL, HOME, 1, self.run.log, additional=True, get=get).status, "failed")
            self.assertEqual(get.call_count, 1)

    def test_http_failure(self):
        page = fetch_website_contents(URL, HOME, 1, self.run.log, get=Mock(side_effect=requests.Timeout))
        self.assertEqual((page.status, page.error), ("failed", "Timeout"))

    def test_same_site_redirect(self):
        responses = [SimpleNamespace(status_code=301, headers={"Location": "/team"}, raise_for_status=lambda: None),
                     SimpleNamespace(status_code=200, headers={"Content-Type": "text/html"}, content=b"fixture", raise_for_status=lambda: None)]
        get = Mock(side_effect=responses)
        with patch("scraper.parse_page", return_value=Page(HOME+"team", "ok", text="fixture")) as parse:
            page = fetch_website_contents(URL, HOME, 1, self.run.log, additional=True, get=get)
        self.assertEqual(page.url, HOME+"team")
        self.assertTrue(all(not c.kwargs["allow_redirects"] for c in get.call_args_list))
        parse.assert_called_once_with(HOME+"team", b"fixture")

    def test_course_html_parser(self):
        try:
            import bs4
        except ImportError:
            self.skipTest("BeautifulSoup unavailable in verification interpreter")
        from scraper import parse_page
        page = parse_page(HOME, b"<title>Site</title><body><nav><a href='/jobs'>Jobs</a></nav><main>Useful<script>ignore</script></main></body>")
        self.assertEqual((page.text, page.title, page.hrefs), ("Useful", "Site", ["/jobs"]))
        self.assertEqual(parse_page(HOME, b"<body><script>junk</script></body>").status, "empty")

