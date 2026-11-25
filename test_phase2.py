"""Offline contract tests for the Phase 2 prompt and selection boundary."""

import json
import unittest
from unittest.mock import Mock

from prompts import build_selection_messages
from utils import normalize_candidates, normalize_url, validate_selection


HOME = "https://company.example/"
CANDIDATES = [HOME + path for path in ("products", "careers", "pricing")]


def item(url):
    return {"type": "company", "url": url, "reason": "Describes the company."}


class NormalizationTests(unittest.TestCase):
    def test_relative_fragments_and_duplicates(self):
        raw = ["products#details", "/careers", "/products", "//WWW.Company.Example:443/products/"]
        self.assertEqual(normalize_candidates(HOME, raw), CANDIDATES[:2])

    def test_http_https_queries_and_configured_www(self):
        home = "https://www.company.example/"
        self.assertEqual(normalize_url(home, "http://company.example:80/news?q=1#top"),
                         "http://www.company.example/news?q=1")

    def test_empty_and_unsupported(self):
        for url in (None, "", " ", "mailto:hi@company.example", "tel:42", "javascript:void(0)",
                    "ftp://company.example/jobs", "data:text/html,x", "https:jobs"):
            with self.subTest(url=url):
                self.assertIsNone(normalize_url(HOME, url))

    def test_external_and_misleading_authorities(self):
        for url in ("https://other.example/jobs", "//company.example.evil.example/jobs",
                    "//fakecompany.example/jobs", "//jobs.company.example/jobs",
                    "//company.example@evil.example/jobs", "//evil.example@company.example/jobs",
                    "//company.example:70000/jobs", "//company.example:444/jobs", "//[broken"):
            with self.subTest(url=url):
                self.assertIsNone(normalize_url(HOME, url))

    def test_homepage_and_policy_pages(self):
        for url in ("/", "#careers", "/?campaign=1", "/jobs/../", "/index.html",
                    "/legal/privacy#details", "/en/privacy-policy.html", "/terms/",
                    "/legal/%74erms-of-service?lang=en", "/policies/terms_of_use", "/dpa"):
            with self.subTest(url=url):
                self.assertIsNone(normalize_url(HOME, url))
        self.assertEqual(normalize_url(HOME, "/privacy-focused-analytics"), HOME + "privacy-focused-analytics")

    def test_prompt_preserves_exact_candidates(self):
        messages = build_selection_messages("Company", CANDIDATES)
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertEqual(json.loads(messages[1]["content"])["candidates"], CANDIDATES)


class ValidationTests(unittest.TestCase):
    def rejected(self, raw_text, reason):
        # A stand-in consumer sees results only after the entire response validates.
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, reason):
            for selected in validate_selection(raw_text, HOME, CANDIDATES):
                fetch(selected["url"])
        fetch.assert_not_called()

    def test_invalid_json(self):
        self.rejected('{"links":', "Expecting")
        self.rejected('{"links": [], "links": []}', "Duplicate JSON key")
        self.rejected('{"links": [], "extra": NaN}', "Invalid JSON")

    def test_root_and_list_shape(self):
        for data in ([], {}, {"links": {}}, {"links": None}):
            with self.subTest(data=data):
                self.rejected(json.dumps(data), "links list")
        self.rejected('{"links": [null]}', "must be an object")

    def test_required_strings(self):
        for field in ("type", "url", "reason"):
            for value in (None, 123, " ", ""):
                record = item(CANDIDATES[0])
                record[field] = value
                self.rejected(json.dumps({"links": [record]}), field)
            del record[field]
            self.rejected(json.dumps({"links": [record]}), field)

    def test_too_many_items(self):
        self.rejected(json.dumps({"links": [item(CANDIDATES[0])] * 4}), "At most three")

    def test_url_absent_or_not_verbatim(self):
        for url in (HOME + "missing", "/products", CANDIDATES[0] + "#top"):
            self.rejected(json.dumps({"links": [item(url)]}), "exact candidate")

    def test_duplicate_normalized_selections(self):
        for duplicate in (CANDIDATES[0], "https://www.company.example/products/#more"):
            self.rejected(json.dumps({"links": [item(CANDIDATES[0]), item(duplicate)]}), "duplicates")

    def test_forbidden_item_rejects_entire_response(self):
        for forbidden in (HOME, HOME + "legal/privacy", HOME + "terms", "https://other.example/jobs"):
            raw = json.dumps({"links": [item(CANDIDATES[0]), item(forbidden)]})
            self.rejected(raw, "forbidden")
            with self.assertRaisesRegex(ValueError, "forbidden"):
                validate_selection(raw, HOME, CANDIDATES + [forbidden])

    def test_valid_empty(self):
        self.assertEqual(validate_selection('{"links":[]}', HOME, CANDIDATES), [])

    def test_valid_selections(self):
        for count in (1, 2, 3):
            items = [item(url) for url in CANDIDATES[:count]]
            selected = validate_selection(json.dumps({"links": items}), HOME, CANDIDATES)
            self.assertEqual(selected, items)
            fetch = Mock()
            for link in selected:
                fetch(link["url"])
            self.assertEqual(fetch.call_count, count)


if __name__ == "__main__":
    unittest.main()
