import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

from config import Settings, Company
from evaluation import prepare_review, verify_review, publish_review, read_text, write_rows
from llm_service import ModelService
from scraper import Page
from storage import Run, read_json, dump_json
from workflow import run_workflow, replay, output_path
from test_outputs import brochure, table, event


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings(tuple(Company(c, "Fixture "+c, f"https://{c.lower()}.test/") for c in "AB"),
                                 output_dir=Path(self.tmp.name))
        self.creates = Mock()
        self.client = N(chat=N(completions=N(create=self.creates)))

    def full_fixture(self):
        calls = []
        def fetch(url, home, additional=False):
            calls.append(url)
            return Page(url,"ok","Fixture","דוגמה",["/team"])
        def answer(**request):
            user = request["messages"][-1]["content"]
            cid = "B" if "Fixture B" in user else "A"
            url = f"https://{cid.lower()}.test/"
            if "Candidate URLs:" in user:
                text = json.dumps(dict(links=[dict(type="team", url=url+"team", reason="candidate evidence")]))
            elif "ארבע עמודות" in user:
                text = table()
            else:
                text = brochure(cid+"1",url)
            if request["stream"]:
                return iter([event(text[:14]), event(None), N(choices=[]), event(text[14:]), event(finish="stop")])
            return N(choices=[N(message=N(content=text),finish_reason="stop")],usage=N(total_tokens=20))
        self.creates.side_effect = answer
        updates = []
        path = run_workflow(self.settings,self.client,fetch=fetch,show=lambda _: None,update=updates.append,mode="mock")
        self.assertEqual(len(calls),4)
        self.assertEqual(len(set(calls)),4)
        self.assertEqual(self.creates.call_count,8)
        self.assertEqual(output_path(path,"B_candidates").read_bytes(), updates[-1].encode("utf-8"))
        return path

    def test_run_replay_and_control(self):
        path = self.full_fixture()
        self.assertEqual(len(replay(path)),6)
        self.assertEqual(self.creates.call_count,8)
        for folder in ("contexts", "prompts"):
            data = [read_json(path/folder/f"{name}.json") for name in ("A_customers","baseline")]
            if folder == "contexts":
                self.assertEqual(*data)
            else:
                self.assertEqual(data[0]["messages"][0],data[1]["messages"][0])
                for key in ("model","stream"):
                    self.assertEqual(data[0][key],data[1][key])
                self.assertNotEqual(data[0]["messages"][1],data[1]["messages"][1])
        events = [json.loads(l) for l in read_text(path/"execution_log.jsonl").splitlines()]
        llm = [e for e in events if e["event"] == "llm"]
        for e in llm:
            for key in ("input_path","context_path","output_path"):
                self.assertTrue((path/e[key]).is_file())
        self.assertNotIn("total_tokens", next(e for e in llm if e["operation"]=="B_candidates"))
        output_path(path,"A_customers").write_bytes(b"altered")
        with self.assertRaises(ValueError):
            replay(path)

    def test_audit_forms(self):
        path = self.full_fixture()
        with self.assertRaises(ValueError):
            verify_review(path)
        file = path/"review/claim_audit.csv"
        rows = list(csv.DictReader(io.StringIO(read_text(file))))
        for row in rows:
            cid = row["brochure"][0]
            row.update(claim="דוגמה",source_id=cid+"1",source_url=f"https://{cid.lower()}.test/",
                       excerpt="דוגמה",verdict="Supported",explanation="synthetic test only")
        write_rows(file,rows)
        prepare_review(path)
        self.assertEqual(verify_review(path),8)
        with self.assertRaises(ValueError):
            publish_review(path)
        form = read_json(path/"review/experiment.json")
        for key in form:
            form[key] = dict(improved_excerpt="דוגמה",baseline_excerpt="דוגמה",finding="synthetic fixture comparison")
        dump_json(path/"review/experiment.json",form)
        self.assertEqual(publish_review(path),8)
        self.assertEqual((path/"artifacts/claim_audit.csv").read_bytes(),file.read_bytes())
        rows[1]["excerpt"] = "absent"
        write_rows(file,rows)
        with self.assertRaises(ValueError):
            verify_review(path)

    def test_partial_is_saved_without_export(self):
        run = Run.new(self.settings.output_dir)
        self.creates.return_value = iter([event("חלק\r\n")])
        service = ModelService(self.client,self.settings,run)
        with self.assertRaises(ValueError):
            service.call("B_candidates","B","candidates","sys","user",{},lambda _:None)
        self.assertEqual((run.root/"responses/B_candidates.txt").read_bytes(), "חלק\r\n".encode())
        self.assertFalse(output_path(run.root,"B_candidates").exists())
        log = [json.loads(l) for l in read_text(run.root/"execution_log.jsonl").splitlines()]
        self.assertEqual(log[-1]["status"],"partial")
        self.assertFalse(log[-1]["success"])

    def test_provider_failure_logged_once_without_token_estimates(self):
        run = Run.new(self.settings.output_dir)
        self.creates.side_effect = TimeoutError()
        service = ModelService(self.client,self.settings,run)
        with self.assertRaises(TimeoutError):
            service.call("A_links","A","both","system","user",{})
        self.creates.assert_called_once()
        start, entry = map(json.loads, read_text(run.root/"execution_log.jsonl").splitlines())
        self.assertEqual((start["event"], entry["event"]), ("llm_started", "llm"))
        self.assertFalse(entry["success"])
        self.assertNotIn("total_tokens",entry)
        failure = read_json(run.root/entry["output_path"])
        self.assertEqual(failure["error"], "TimeoutError")
        self.assertIsNone(failure["http_status"])
        self.assertFalse(failure["retryable"])

