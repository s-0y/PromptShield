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
from agent.llm_client import Completion, LLMClient, LLMError, build_summary_messages
from agent.tools import REVIEW_INBOX, MockToolSession


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]


def store_tool_response(
    session: MockToolSession, completion: Completion, *, mock: bool
) -> tuple[str, str | None]:
    if completion.tool_calls is not None:
        result = session.model_call(completion.tool_calls, completion.finish_reason, mock=mock)
        if completion.finish_reason != "tool_calls":
            return "incomplete", None
    elif completion.finish_reason == "stop":
        # Some providers return a plain-text summary when offered an optional tool.
        result = session.application_call("save_summary", {"summary": completion.text})
    else:
        return "incomplete", completion.text
    if not result.executed:
        return "blocked", None
    return "ok", result.value


def run_case(
    client: LLMClient, sample: dict, mode: str, source: str, label: str | None, run_id: str,
    *, review_transfer: str | None = None,
) -> dict:
    if review_transfer is not None and (
        mode != "guarded-tools" or review_transfer not in {"request", "approve"}
    ):
        raise ValueError("review transfer requires guarded-tools mode and request or approve")
    session = None
    document = sample["text"]
    prompt_mode = mode
    if mode == "guarded-tools":
        session = MockToolSession(sample["id"], document, approve_transfer=review_transfer == "approve")
        read = session.application_call("read_public", {"document_id": sample["id"]})
        if not read.executed or read.value is None:
            raise ValueError(f"Selected document could not be read: {read.reason}")
        document = read.value
        prompt_mode = "boundary"
    messages = build_summary_messages(document, prompt_mode)
    record = {
        "schema_version": 2 if session else 1,
        "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sample_id": sample["id"],
        "source": source,
        "expected_label": label,
        "sample": sample,
        "document_sha256": hashlib.sha256(sample["text"].encode("utf-8")).hexdigest(),
        "prompt_version": "summary-v2",
        "prompt_mode": prompt_mode,
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
        if session is None:
            completion = client.complete(messages)
            status = "ok" if completion.finish_reason == "stop" else "incomplete"
            response = completion.text
        else:
            completion = client.complete(messages, offer_save_tool=True)
            status, response = store_tool_response(session, completion, mock=record["is_mock"])
            if status == "ok" and review_transfer:
                session.application_call("mock_transfer", {"destination": REVIEW_INBOX})
        record.update(
            response=response, response_model=completion.model,
            finish_reason=completion.finish_reason, usage=completion.usage,
            status=status,
        )
    except LLMError as exc:
        record["error"] = str(exc)
    if session is not None:
        record["workflow"] = "guarded-tools"
        record["mock_tools"] = session.snapshot()
    record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return record


def add_common_arguments(parser: argparse.ArgumentParser, *, single_case: bool = False) -> None:
    parser.add_argument("--provider", choices=("mock", "api"), help="Override local provider setting")
    modes = ("baseline", "boundary", "guarded-tools") if single_case else ("baseline", "boundary")
    parser.add_argument("--mode", choices=modes, default="baseline")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output-dir", type=Path, default=Path("results"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser, single_case=True)
    parser.add_argument(
        "--review-transfer", choices=("request", "approve"),
        help="Simulate a copy of the saved summary to the local review inbox, with or without approval",
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--id", required=True)
    args = parser.parse_args()
    if args.review_transfer and args.mode != "guarded-tools":
        parser.error("--review-transfer requires --mode guarded-tools")
    try:
        sample = select_record(args.dataset, args.id)
        load_env(args.env_file)
        client = LLMClient(Settings.from_env(args.provider))
        run_id = new_run_id()
        directory = args.output_dir / run_id
        directory.mkdir(parents=True, exist_ok=False)
        result = run_case(
            client, sample, args.mode, str(args.dataset), None, run_id,
            review_transfer=args.review_transfer,
        )
        path = directory / "result.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    output = {key: result[key] for key in ("status", "is_mock", "response", "error")}
    output["result_file"] = str(path)
    if "mock_tools" in result:
        output["tool_events"] = result["mock_tools"]["events"]
        output["transfer_receipt"] = result["mock_tools"]["transfer_receipt"]
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
