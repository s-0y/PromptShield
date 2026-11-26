"""Run one sample and save a reproducible JSON experiment record."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import uuid

from agent.config import Settings, load_env
from agent.datasets import select_record
from agent.llm_client import LLMClient, LLMError, build_summary_messages


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]


def run_case(client: LLMClient, sample: dict, mode: str, source: str, label: str | None, run_id: str) -> dict:
    messages = build_summary_messages(sample["text"], mode)
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sample_id": sample["id"],
        "source": source,
        "expected_label": label,
        "sample": sample,
        "document_sha256": hashlib.sha256(sample["text"].encode("utf-8")).hexdigest(),
        "prompt_version": "summary-v2",
        "prompt_mode": mode,
        "messages": messages,
        "configuration": client.settings.public_metadata(),
        "is_mock": client.settings.provider == "mock",
        "status": "error",
        "response": None,
        "response_model": None,
        "finish_reason": None,
        "usage": {},
        "error": None,
        "attack_success": None,
        "normal_task_success": None,
    }
    started = time.perf_counter()
    try:
        completion = client.complete(messages)
        record.update(
            response=completion.text, response_model=completion.model,
            finish_reason=completion.finish_reason, usage=completion.usage,
            status="ok" if completion.finish_reason == "stop" else "incomplete",
        )
    except LLMError as exc:
        record["error"] = str(exc)
    record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return record


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=("mock", "api"), help="Override local provider setting")
    parser.add_argument("--mode", choices=("baseline", "boundary"), default="baseline")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output-dir", type=Path, default=Path("results"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--id", required=True)
    args = parser.parse_args()
    try:
        sample = select_record(args.dataset, args.id)
        load_env(args.env_file)
        client = LLMClient(Settings.from_env(args.provider))
        run_id = new_run_id()
        directory = args.output_dir / run_id
        directory.mkdir(parents=True, exist_ok=False)
        result = run_case(client, sample, args.mode, str(args.dataset), None, run_id)
        path = directory / "result.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": result["status"], "is_mock": result["is_mock"], "result_file": str(path), "response": result["response"], "error": result["error"]}, ensure_ascii=False, indent=2))
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
