import unittest
from types import SimpleNamespace as N

from config import Company
from context_manager import build_context
from llm_service import aggregate_stream
from prompt_builder import DIMENSIONS, MISSING, get_brochure_user_prompt
from validators import validate_brochure, validate_comparison


def source(sid, text, status="ok"):
    return dict(source_id=sid, company_id=sid[0], status=status, text=text, title=sid+" title",
                url=f"https://{sid[0].lower()}.test/", retrieved_at="2020-01-01T00:00:00Z")


def brochure(sid, url, count=205):
    return "# כותרת\n" + "דוגמה "*(count-3) + f"[{sid}]\n\n## מקורות\n- [{sid}] {url}"


def table():
    return ("| ממד | חברה א | חברה ב | הבדל |\n|---|---|---|---|\n" +
            "\n".join(f"| {d} | מידע [A1] | מידע [B1] | {MISSING} |" for d in DIMENSIONS) +
            "\n\nההשוואה מבוססת על פרסומי החברות. יש לברר את תנאי השירות.")


def event(text=None, finish=None):
    return N(choices=[N(delta=N(content=text), finish_reason=finish)])


class ContextTests(unittest.TestCase):
    def test_fair_budget(self):
        records = [source("A1", "x"*150000), source("A2", "yy"), source("A3", "z"*200),
                   source("A4", "bad", "failed"), source("B1", "", "empty")]
        ctx = build_context(records, 22)
        self.assertEqual([d["supplied_chars"] for d in ctx["decisions"]], [10, 2, 10, 0, 0])
        self.assertEqual([d["state"] for d in ctx["decisions"]], ["truncated","included","truncated","omitted","omitted"])
        self.assertEqual([d["reason"] for d in ctx["decisions"]][-2:], ["failed","empty"])
        for original, entry in zip(records, ctx["evidence"]):
            self.assertEqual((original["source_id"], original["title"], original["url"]),
                             (entry["source_id"], entry["title"], entry["url"]))
        prompt = get_brochure_user_prompt(Company("A","בדיקה",records[0]["url"]), "customers", ctx["text"])
        self.assertIn("200–300", prompt)
        self.assertTrue(prompt.endswith(ctx["text"]))

    def test_shared_budget_and_ties(self):
        records = [source(sid,"x"*100) for sid in ("A1","A2","B1","B2")]
        self.assertEqual([len(e["text"]) for e in build_context(records,9)["evidence"]], [3,2,2,2])
        self.assertEqual(build_context(records,1)["decisions"][-1]["state"], "omitted")


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.records = [source("A1","x"), source("A2","", "empty"),source("A3","error","failed"),source("B1","y")]
        self.ctx = build_context(self.records[:3], 1)
        self.url = self.records[0]["url"]

    def test_word_count_boundaries(self):
        for n in (199,200,300,301):
            text = brochure("A1",self.url,n)
            if n in (199,301):
                with self.assertRaises(ValueError):
                    validate_brochure(text,self.ctx,self.records,"A")
            else:
                self.assertEqual(validate_brochure(text,self.ctx,self.records,"A")["word_count"],n)

    def test_wrong_citations_and_refs(self):
        text = brochure("A1", self.url)
        records = [source("A1","first"), source("A2","eligible but omitted")]
        with self.assertRaises(ValueError):
            validate_brochure(text.replace("A1","A2"), build_context(records,1),records,"A")
        for bad in ("A2","A3","A4","B1","Z9","a1","A1, A2"):
            with self.assertRaises(ValueError):
                validate_brochure(text.replace("[A1]",f"[{bad}]"), self.ctx,self.records,"A")
        for bad in (text.replace(self.url,"https://wrong.test"), text + "\nextra", text.replace("## מקורות","## אחר"),
                    text.replace("דוגמה","example")):
            with self.assertRaises(ValueError):
                validate_brochure(bad,self.ctx,self.records,"A")

    def test_comparison(self):
        ctx = build_context(self.records, 5)
        self.assertEqual(validate_comparison(table(),ctx,self.records,DIMENSIONS)["dimensions"], DIMENSIONS)
        for invalid in (table().replace("[B1]","[A1]"),table().replace(DIMENSIONS[1],"אחר"),
                        table().replace(MISSING,"הבדל ללא ראיה"),
                        table()+"\n| ממד נוסף | א | ב | ג |", table().split("\n\n")[0]):
            with self.assertRaises(ValueError):
                validate_comparison(invalid,ctx,self.records,DIMENSIONS)


class StreamTests(unittest.TestCase):
    def test_noise_and_exact_updates(self):
        events = [N(), N(choices=[]), event(None), event(""), N(choices=[N()]),
                  event("אב "), event("\n"),event(" ג"),event(finish="stop"), N(choices=[],usage=N(total_tokens=4))]
        updates = []
        result, error, usage = aggregate_stream(events, updates.append)
        self.assertEqual(updates, ["אב ", "אב \n", "אב \n ג"])
        self.assertEqual((result, error, usage), ("אב \n ג",None,{"total_tokens":4}))

    def test_partial_stream(self):
        def broken():
            yield event("חלק")
            raise ConnectionError()
        for events in (broken(),[event("חלק")],[event("חלק", "length")]):
            text, error, _ = aggregate_stream(events,lambda _: None)
            self.assertEqual(text,"חלק")
            self.assertTrue(error)

