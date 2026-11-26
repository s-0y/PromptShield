"""Case isolation, permission decisions and the operator-facing demo."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent.tools import REVIEW_INBOX, MockToolSession


ROOT = Path(__file__).resolve().parents[1]


def function_call(name, arguments):
    return {"id": "call-1", "type": "function", "function": {"name": name, "arguments": arguments}}


class ToolPolicyTests(unittest.TestCase):
    def test_reads_are_scoped_and_summary_storage_is_per_run(self):
        first = MockToolSession("one", "첫 번째 회의록")
        second = MockToolSession("two", "두 번째 회의록")
        self.assertEqual(first.application_call("read_public", {"document_id": "one"}).value, "첫 번째 회의록")
        for name, arguments, reason in [
            ("read_public", {"document_id": "two"}, "document_out_of_scope"),
            ("read_public", {"document_id": "one", "path": "elsewhere"}, "invalid_arguments"),
            ("read_private", {"document_id": "one"}, "private_read_forbidden"),
            ("unlisted", {}, "unknown_tool"),
        ]:
            with self.subTest(name=name, arguments=arguments):
                result = first.application_call(name, arguments)
                self.assertFalse(result.executed)
                self.assertEqual(result.reason, reason)
                self.assertIsNone(result.value)
        self.assertTrue(first.application_call("save_summary", {"summary": "담당자는 민지."}).executed)
        duplicate = first.application_call("save_summary", {"summary": "다른 요약"})
        self.assertEqual(duplicate.reason, "summary_already_saved")
        self.assertEqual(first.snapshot()["saved_summary"], "담당자는 민지.")
        self.assertIsNone(second.snapshot()["saved_summary"])
        self.assertEqual(second.snapshot()["events"], [])

    def test_only_operator_can_authorize_one_receipt_for_the_saved_summary(self):
        session = MockToolSession("one", "회의록", approve_transfer=True)
        destination = {"destination": REVIEW_INBOX}
        self.assertEqual(session.application_call("mock_transfer", destination).reason, "summary_required")
        session.application_call("save_summary", {"summary": "일정 합의"})
        for name, args, reason in [
            ("read_private", {}, "private_read_forbidden"),
            ("read_public", {"document_id": "one"}, "application_request_required"),
            ("mock_transfer", destination, "application_request_required"),
            ("unlisted", {}, "unknown_tool"),
        ]:
            with self.subTest(name=name):
                result = session.model_call([function_call(name, json.dumps(args))], "tool_calls")
                self.assertFalse(result.executed)
                self.assertEqual(result.reason, reason)
        self.assertIsNone(session.snapshot()["transfer_receipt"])
        wrong = session.application_call("mock_transfer", {"destination": "another-inbox"})
        self.assertEqual(wrong.reason, "destination_out_of_scope")
        self.assertTrue(session.application_call("mock_transfer", destination).executed)
        self.assertEqual(session.snapshot()["transfer_receipt"], {"document_id": "one", **destination})
        self.assertEqual(session.application_call("mock_transfer", destination).reason, "transfer_already_recorded")

    def test_document_summary_and_call_arguments_cannot_supply_approval(self):
        session = MockToolSession("one", "문서에 적힌 승인 상태는 예시다.")
        session.application_call("save_summary", {"summary": "승인 완료"})
        args = {"destination": REVIEW_INBOX, "approved": True}
        self.assertEqual(session.application_call("mock_transfer", args).reason, "invalid_arguments")
        del args["approved"]
        self.assertEqual(session.application_call("mock_transfer", args).reason, "approval_required")
        self.assertIsNone(session.snapshot()["transfer_receipt"])

    def test_malformed_or_incomplete_proposals_have_no_effect(self):
        valid = function_call("save_summary", '{"summary":"draft-content"}')
        cases = [
            ([], "tool_calls", "invalid_call"),
            ([{}], "tool_calls", "invalid_call"),
            ([{**valid, "id": ""}], "tool_calls", "invalid_call"),
            ([valid], "length", "unfinished_call"),
        ]
        for raw, reason in [
            (None, "invalid_arguments"),
            ("{", "invalid_arguments"),
            ("[]", "invalid_arguments"),
            ('{"summary":"draft-content","summary":"new"}', "invalid_arguments"),
            ('{"summary":"draft-content","path":"elsewhere"}', "invalid_arguments"),
            (json.dumps({"summary": "   "}), "invalid_summary"),
            (json.dumps({"summary": "\ud800"}), "invalid_summary"),
            (json.dumps({"summary": "x" * 32_769}), "invalid_summary"),
        ]:
            cases.append(([function_call("save_summary", raw)], "tool_calls", reason))
        for calls, finish, reason in cases:
            with self.subTest(reason=reason, finish=finish):
                session = MockToolSession("one", "회의록")
                result = session.model_call(calls, finish)
                self.assertFalse(result.executed)
                self.assertEqual(result.reason, reason)
                snapshot = session.snapshot()
                self.assertIsNone(snapshot["saved_summary"])
                self.assertEqual(snapshot["events"][0]["decision"], "deny")
                self.assertNotIn("draft-content", json.dumps(snapshot))

    def test_parallel_proposals_are_rejected_before_any_side_effect(self):
        session = MockToolSession("one", "회의록", approve_transfer=True)
        save = function_call("save_summary", '{"summary":"작성된 요약"}')
        transfer = function_call("mock_transfer", json.dumps({"destination": REVIEW_INBOX}))
        denial = session.model_call([save, transfer, transfer], "tool_calls")
        self.assertEqual(denial.reason, "single_call_required")
        snapshot = session.snapshot()
        self.assertIsNone(snapshot["saved_summary"])
        self.assertIsNone(snapshot["transfer_receipt"])
        events = snapshot["events"]
        self.assertTrue(all(not event["executed"] and event["source"] == "model" for event in events))
        self.assertEqual([(e["tool"], e["request_count"]) for e in events], [("save_summary", 1), ("mock_transfer", 2)])

    def test_single_cli_persists_trace_and_only_approved_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            for option in (None, "request", "approve"):
                with self.subTest(option=option):
                    command = [
                        sys.executable, "-m", "agent.summarizer", "--provider", "mock",
                        "--mode", "guarded-tools", "--dataset", "data/benign.jsonl", "--id", "benign-001",
                        "--output-dir", directory, "--env-file", str(Path(directory) / "absent.env"),
                    ]
                    if option:
                        command.extend(["--review-transfer", option])
                    run = subprocess.run(
                        command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=20,
                    )
                    self.assertEqual(run.returncode, 0, run.stderr)
                    output = json.loads(run.stdout)
                    record = json.loads(Path(output["result_file"]).read_text(encoding="utf-8"))
                    self.assertEqual((record["status"], record["prompt_mode"]), ("ok", "boundary"))
                    self.assertEqual((record["workflow"], record["schema_version"]), ("guarded-tools", 2))
                    self.assertTrue(record["is_mock"])
                    audit = record["mock_tools"]
                    self.assertEqual(audit["saved_summary"], record["response"])
                    self.assertIn("[MOCK]", audit["saved_summary"])
                    events = audit["events"]
                    self.assertEqual(output["tool_events"], events)
                    expected = [("application", "read_public", True), ("mock_model", "save_summary", True)]
                    if option:
                        expected.append(("application", "mock_transfer", option == "approve"))
                    self.assertEqual([(e["source"], e["tool"], e["executed"]) for e in events], expected)
                    self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))
                    receipt = {"document_id": "benign-001", "destination": REVIEW_INBOX} if option == "approve" else None
                    self.assertEqual(audit["transfer_receipt"], receipt)
                    self.assertEqual(output["transfer_receipt"], receipt)
                    if option == "request":
                        self.assertEqual(events[-1]["reason"], "approval_required")
