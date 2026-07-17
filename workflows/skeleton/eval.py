#!/usr/bin/env python3
"""Evaluate workflow responses against test prompts."""

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from langgraph.types import Command

from graph import graph

PROMPTS_PATH = Path(__file__).parent / "eval_prompts.json"
RESULTS_DIR = Path(__file__).parent / "eval_results"


def run_one(case: Dict[str, Any]) -> Dict[str, Any]:
    """Run a single evaluation case."""
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    started = time.perf_counter()
    result = graph.invoke(
        {"tenant_id": case["tenant_id"], "prompt": case["prompt"]},
        config=config,
    )
    result = graph.invoke(Command(resume=True), config=config)
    wall_ms = int((time.perf_counter() - started) * 1000)

    return {
        "id": case["id"],
        "tenant_id": case["tenant_id"],
        "model": result["model"],
        "prompt": case["prompt"],
        "output": result.get("output", ""),
        "latency_ms": result["latency_ms"],
        "wall_ms": wall_ms,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
    }


def main() -> None:
    """Run all evaluation cases."""
    cases: List[Dict[str, Any]] = json.loads(
        PROMPTS_PATH.read_text(encoding="utf-8")
    )
    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"run_{time.strftime('%Y-%m-%d_%H%M%S')}.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] {case['id']} ({case['tenant_id']})...",
                  flush=True)
            try:
                record = run_one(case)
            except Exception as exc:
                record = {
                    "id": case["id"],
                    "tenant_id": case["tenant_id"],
                    "prompt": case["prompt"],
                    "error": str(exc),
                }
            f.write(json.dumps(record) + "\n")
            f.flush()

    print(f"\nWrote {len(cases)} results to {out_path}")


if __name__ == "__main__":
    main()