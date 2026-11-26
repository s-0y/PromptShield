"""Evaluate labeled samples independently and persist each screening or model result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.config import Settings, load_env
from agent.datasets import load_records
from agent.input_risk import RULESET_VERSION
from agent.llm_client import LLMClient
from agent.summarizer import add_common_arguments, new_run_id, run_case


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    parser.add_argument("--benign", type=Path, default=Path("data/benign.jsonl"))
    parser.add_argument("--attacks", type=Path, default=Path("data/attacks.jsonl"))
    args = parser.parse_args()
    try:
        cases = [(sample, path, label) for path, label in ((args.benign, "benign"), (args.attacks, "attack")) for sample in load_records(path)]
        ids = [sample["id"] for sample, _, _ in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Sample IDs must be unique across both datasets")
        load_env(args.env_file)
        client = LLMClient(Settings.from_env(args.provider))
        run_id = new_run_id()
        directory = args.output_dir / run_id
        directory.mkdir(parents=True, exist_ok=False)
        counts = {"ok": 0, "error": 0, "incomplete": 0}
        screened = args.mode == "screened"
        if screened:
            counts["held"] = 0
            decisions = {label: {"proceed": 0, "warn": 0, "hold": 0} for label in ("benign", "attack")}
            model_calls = 0
        with (directory / "results.jsonl").open("w", encoding="utf-8") as stream:
            for sample, path, label in cases:
                result = run_case(client, sample, args.mode, str(path), label, run_id)
                stream.write(json.dumps(result, ensure_ascii=False) + "\n")
                stream.flush()
                counts[result["status"]] += 1
                if screened:
                    decisions[label][result["input_risk"]["decision"]] += 1
                    model_calls += int(result["model_called"])
        summary = {
            "run_id": run_id, "total": len(cases), "counts": counts,
            "is_mock": client.settings.provider == "mock",
            "prompt_mode": "boundary" if screened else args.mode, "configuration": client.settings.public_metadata(),
            "grading": "not_performed", "results_file": str(directory / "results.jsonl"),
        }
        if screened:
            benign = decisions["benign"]
            attack = decisions["attack"]
            # Both labeled files were validated as nonempty before the first case.
            summary["workflow"] = "screened"
            summary["input_screening"] = {
                "ruleset_version": RULESET_VERSION, "by_label": decisions, "model_calls": model_calls,
                "benign_warning_rate": benign["warn"] / sum(benign.values()),
                "benign_hold_rate": benign["hold"] / sum(benign.values()),
                "attack_flag_rate": (attack["warn"] + attack["hold"]) / sum(attack.values()),
            }
        (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if counts["error"] or counts["incomplete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
