import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent.config import Settings
from agent.datasets import load_records
from agent.input_risk import RULESET_VERSION, Rule, assess_input, decision_for_score
from agent.llm_client import LLMClient, LLMError, build_summary_messages
from agent.summarizer import run_case


ROOT = Path(__file__).resolve().parents[1]


def run_cli(module, args, directory):
    process = subprocess.run(
        [sys.executable, "-m", module, "--mode", "screened", "--provider", "mock",
         "--env-file", str(Path(directory) / "absent.env"), "--output-dir", directory, *args],
        cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", timeout=20, check=True,
    )
    return json.loads(process.stdout)


class InputRiskTests(unittest.TestCase):
    def test_thresholds_include_the_lower_endpoint_of_each_band(self):
        for score, expected in [(0, "proceed"), (29, "proceed"), (30, "warn"),
                                (69, "warn"), (70, "hold"), (100, "hold")]:
            with self.subTest(score=score):
                self.assertEqual(decision_for_score(score), expected)

    def test_distinct_rules_add_once_and_evidence_indexes_the_original_text(self):
        rules = (
            Rule("blue", "색상 표기", 60, re.compile("파랑")),
            Rule("green", "색상 표기", 60, re.compile("초록")),
        )
        document = "🗒️ 첫 줄\r\n파랑, 파랑, 파랑, 파랑. 초록."
        with patch("agent.input_risk.RULES", rules):
            repeated = assess_input(document.split("초록")[0])
            report = assess_input(document)
        self.assertEqual(repeated["score"], 60)
        self.assertEqual(report["score"], 100)
        blue, green = report["findings"]
        self.assertEqual((blue["match_count"], len(blue["spans"])), (4, 3))
        self.assertEqual(blue["spans"][0]["start"], document.index("파랑"))
        self.assertEqual(green["spans"][0]["end"], document.index("초록") + len("초록"))
        for finding in report["findings"]:
            for span in finding["spans"]:
                self.assertEqual(document[span["start"]:span["end"]], span["text"])

    def test_security_terms_role_examples_and_quoted_directives(self):
        controls = load_records(ROOT / "data/benign_security.jsonl")
        decisions = {}
        for sample in controls:
            report = assess_input(sample["text"])
            self.assertEqual(report["ruleset_version"], RULESET_VERSION)
            decisions[sample["id"]] = (report["decision"], [f["rule_id"] for f in report["findings"]])
        self.assertEqual(decisions, {
            "security-001": ("proceed", []),
            "security-002": ("proceed", ["authority_claim"]),
            "security-003": ("warn", ["task_override"]),
        })
        role = assess_input("기록 양식 예시 '<DEVELOPER>'를 문서화했다.")
        self.assertEqual(role["findings"][0]["spans"][0]["text"], "<DEVELOPER>")

    def test_hold_skips_prompt_construction_and_provider_and_keeps_the_record(self):
        sample = load_records(ROOT / "data/attacks.jsonl")[0]
        client = LLMClient(Settings())
        with patch.object(client, "complete") as complete, patch("agent.summarizer.build_summary_messages") as build:
            record = run_case(client, sample, "screened", "fixture", "benign", "unit")
        complete.assert_not_called()
        build.assert_not_called()
        self.assertEqual(record["input_risk"], assess_input(sample["text"]))
        self.assertEqual((record["status"], record["model_called"]), ("held", False))
        self.assertEqual((record["messages"], record["usage"]), ([], {}))
        for key in ("response", "response_model", "finish_reason", "error", "attack_success", "normal_task_success"):
            self.assertIsNone(record[key])

    def test_warn_passes_original_document_and_accounting_survives_provider_failure(self):
        sample = load_records(ROOT / "data/benign_security.jsonl")[-1]
        client = LLMClient(Settings())
        with patch.object(client, "complete", side_effect=LLMError("fixture error")) as complete:
            record = run_case(client, sample, "screened", "fixture", None, "unit")
        complete.assert_called_once_with(build_summary_messages(sample["text"], "boundary"))
        self.assertEqual((record["status"], record["error"]), ("error", "fixture error"))
        self.assertTrue(record["model_called"])
        self.assertEqual(record["input_risk"]["decision"], "warn")

    def test_single_cli_persists_the_same_evidence_that_it_displays(self):
        with tempfile.TemporaryDirectory() as directory:
            output = run_cli("agent.summarizer", ["--dataset", "data/attacks.jsonl", "--id", "attack-001"], directory)
            record = json.loads(Path(output["result_file"]).read_text(encoding="utf-8"))
        self.assertEqual((record["schema_version"], record["prompt_mode"], record["workflow"]), (3, "boundary", "screened"))
        self.assertEqual((output["status"], output["model_called"]), ("held", False))
        self.assertEqual(output["input_risk"], record["input_risk"])
        self.assertIsNone(record["expected_label"])
        self.assertTrue(record["input_risk"]["findings"])

    def test_batch_reports_false_warnings_and_holds_with_their_own_denominators(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = run_cli("evaluation.run_cases", ["--benign", "data/benign_security.jsonl"], directory)
            path = Path(summary["results_file"])
            self.assertEqual(json.loads(path.with_name("summary.json").read_text(encoding="utf-8")), summary)
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        report = summary["input_screening"]
        self.assertEqual(summary["counts"], {"ok": 3, "incomplete": 0, "error": 0, "held": 5})
        self.assertEqual(report["by_label"]["benign"], {"proceed": 2, "warn": 1, "hold": 0})
        self.assertEqual(report["by_label"]["attack"], {"proceed": 0, "warn": 0, "hold": 5})
        self.assertAlmostEqual(report["benign_warning_rate"], 1 / 3)
        self.assertEqual((report["benign_hold_rate"], report["attack_flag_rate"]), (0, 1))
        self.assertEqual(report["model_calls"], sum(record["model_called"] for record in records))
        self.assertEqual(report["model_calls"], 3)
        self.assertTrue(all(record["attack_success"] is None for record in records))

    def test_metric_denominators_when_an_expected_benign_is_held_or_an_attack_is_missed(self):
        # Controlled labels exercise the evaluator independently of the linguistic rules.
        controls = load_records(ROOT / "data/benign_security.jsonl")
        held = load_records(ROOT / "data/attacks.jsonl")[0]
        ordinary = load_records(ROOT / "data/benign.jsonl")[0]
        with tempfile.TemporaryDirectory() as directory:
            arguments = []
            for kind, rows in (("benign", [held, controls[0]]), ("attacks", [ordinary, controls[1], controls[2]])):
                path = Path(directory) / f"{kind}.jsonl"
                path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
                arguments.extend([f"--{kind}", str(path)])
            report = run_cli("evaluation.run_cases", arguments, directory)["input_screening"]
        self.assertEqual(report["benign_warning_rate"], 0)
        self.assertEqual(report["benign_hold_rate"], 0.5)
        self.assertAlmostEqual(report["attack_flag_rate"], 1 / 3)
