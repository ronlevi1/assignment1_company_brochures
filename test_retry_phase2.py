"""Offline tests for scoped Phase 2 retries and saved selection merging."""

import json
import subprocess
import sys
import unittest
import shutil
from pathlib import Path
import shutil
from unittest.mock import patch

import retry_phase2


class RetryArgumentTests(unittest.TestCase):
    def run_main(self, *args):
        with patch.object(sys, "argv", ["retry_phase2.py", *args]):
            return retry_phase2.main()

    def test_company_a_attempt_does_not_overwrite_company_b(self):
        root = Path(".retry-test-fixture")
        saved = root / "runs/phase2-for-20261124T144231622541Z"
        retry = saved.with_name(saved.name + "-attempt-02")
        prior_b = {"company": "Company B", "outcome": "accepted", "validation": "valid",
                   "links": [{"type": "products", "url": "https://company-b.example/products",
                              "reason": "Synthetic saved response."}]}
        try:
            (retry / "B").mkdir(parents=True)
            (retry / "B/result.json").write_text(json.dumps(prior_b), encoding="utf-8")
            for company_id in ("A", "B"):
                folder = saved / company_id
                folder.mkdir(parents=True)
                (folder / "input.json").write_text(json.dumps({
                    "model": retry_phase2.MODEL,
                    "company": f"Company {company_id}",
                    "messages": [{"role": "user", "content": "synthetic saved prompt"}],
                    "response_format": {"type": "json_object"},
                }), encoding="utf-8")

            with (
                patch.object(retry_phase2, "Path", side_effect=lambda value: root / value),
                patch.object(retry_phase2, "check_connectivity", return_value=True) as connectivity,
                patch.object(retry_phase2, "create_client") as create_client,
                patch.object(sys, "argv", ["retry_phase2.py", "--execute", "--company", "A"]),
            ):
                with patch.object(retry_phase2, "select_once", side_effect=lambda _, folder: (
                    (folder / "result.json").write_text(
                        json.dumps({"company": "Company A", "outcome": "call_failed",
                                    "validation": "not_run"}), encoding="utf-8"
                    )
                )) as select_once:
                    retry_phase2.main()
                    retry_phase2.main()
                self.assertEqual(select_once.call_count, 2)
                self.assertEqual(
                    [call.args[1] for call in select_once.call_args_list],
                    [retry / "A", saved.with_name(saved.name + "-attempt-03") / "A"],
                )
                self.assertEqual(connectivity.call_count, 2)
                self.assertEqual(create_client.call_count, 2)
            self.assertEqual(
                json.loads((retry / "B/result.json").read_text(encoding="utf-8")), prior_b
            )
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_rejects_invalid_company(self):
        result = subprocess.run(
            [sys.executable, "retry_phase2.py", "--execute", "--company", "C"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main()
