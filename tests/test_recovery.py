"""Regression tests for mixed-script Hebrew, bounded sampling and a spare source slot."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

from config import Settings, Company
from evaluation import accepted_text, read_text
from llm_service import ModelService
from scraper import Page
from source_manager import fetch_page_and_all_relevant_links
from storage import Run, read_json
from validators import hebrew_prose
from workflow import run_workflow, replay
from test_outputs import brochure, table, event


def selection(*urls):
    return json.dumps({"links": [dict(type="team", url=url, reason="Candidate evidence") for url in urls]})


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.companies = [Company(cid, "Fixture " + cid, f"https://{cid.lower()}.test/") for cid in "AB"]
        self.settings = Settings(tuple(self.companies), output_dir=Path(tmp.name))
        self.run = Run.new(Path(tmp.name))

    def test_primary_language_with_technical_terms(self):
        hebrew_prose("חברת Fathom Analytics מפרסמת מידע בעברית על חיבור המערכת באמצעות API [A1].")
        for foreign in ("English prose with a single עברית word", "全部内容均为其他语言 ורק מילה אחת " + "示例 "*25, "[A1]"):
            with self.assertRaises(ValueError):
                hebrew_prose(foreign)

    def test_no_fifth_page_after_failure(self):
        c = self.companies[0]
        home = Page(c.url, "ok", text="fixture", hrefs=["/a","/b","/c","/d"])
        fetch = Mock(side_effect=[home] + [Page(c.url+k, "empty") for k in "abc"])
        extra = Mock()
        sources = fetch_page_and_all_relevant_links(self.run, c, fetch,
                                lambda *_: selection(*(c.url+k for k in "abc")), extra)
        self.assertEqual([s["source_id"] for s in sources], ["A1","A2","A3","A4"])
        self.assertEqual(fetch.call_count, 4)
        extra.assert_not_called()

    def test_invalid_supplement_causes_zero_supplemental_requests(self):
        c = self.companies[0]
        fetch = Mock(side_effect=[Page(c.url,"ok",text="home",hrefs=["/a","/b","/c","/d"]),
                                  Page(c.url+"a","empty"), Page(c.url+"b","ok",text="team")])
        with self.assertRaisesRegex(ValueError, "remaining source slots"):
            fetch_page_and_all_relevant_links(self.run,c,fetch,lambda *_: selection(c.url+"a",c.url+"b"),
                                              lambda *_: selection(c.url+"c",c.url+"d"))
        self.assertEqual(fetch.call_count,3)
        self.assertFalse(read_json(self.run.root/"data/A_alternative_selection.json")["valid"])
        self.assertEqual(len(read_json(self.run.root/"data/A_sources.json")),3)

    def test_invalid_second_sample_stops(self):
        response = N(choices=[N(message=N(content="bad"),finish_reason="stop")])
        create = Mock(return_value=response)
        service = ModelService(N(chat=N(completions=N(create=create))),self.settings,self.run)
        def invalid(_):
            raise ValueError("wrong length")
        with self.assertRaisesRegex(ValueError,"wrong length"):
            service.validated_writing("baseline","A","customers","system","user",{},invalid)
        self.assertEqual(create.call_count,2)
        self.assertTrue((self.run.root/"responses/baseline.attempt2.txt").exists())

    def test_replay_with_replacement_and_repeat(self):
        def fetch(url, home, additional=False):
            if not additional:
                return Page(home,"ok",text="fixture "*200,hrefs=["/team", "/work"])
            if url == "https://a.test/team":
                return Page(url,"failed",error="fixture timeout")
            return Page(url,"ok",text="team")
        first = True
        def answer(**request):
            nonlocal first
            user = request["messages"][-1]["content"]
            cid = "B" if "Fixture B" in user else "A"
            url = f"https://{cid.lower()}.test/"
            if "Candidate URLs:" in user:
                value = selection(url+("work" if user.startswith("Evidence gap:") else "team"))
            elif "ארבע עמודות" in user:
                value = table()
            elif first:
                first = False
                value = "טיוטה קצרה"
            else:
                value = brochure(cid+"1",url)
            if request["stream"]:
                return iter([event(value),event(finish="stop")])
            return N(choices=[N(message=N(content=value),finish_reason="stop")])
        create = Mock(side_effect=answer)
        run = run_workflow(self.settings,N(chat=N(completions=N(create=create))),fetch=fetch,show=lambda _:None,mode="mock")
        self.assertEqual(create.call_count,10)
        self.assertEqual(replay(run)["A_customers"]["accepted_attempt"],2)
        self.assertEqual(accepted_text(run,"A_customers"),brochure("A1","https://a.test/"))
        self.assertEqual(read_text(run/"responses/A_customers.txt"),"טיוטה קצרה")
        self.assertEqual(read_json(run/"prompts/A_customers.json"),read_json(run/"prompts/A_customers.attempt2.json"))
        self.assertNotIn("טיוטה קצרה", read_text(run/"review/evidence.md"))
        sources = read_json(run/"data/A_sources.json")
        self.assertEqual([s["status"] for s in sources],["ok","failed","ok"])
        self.assertEqual(read_json(run/"contexts/A_alternative.json")["candidates"],["https://a.test/work"])

