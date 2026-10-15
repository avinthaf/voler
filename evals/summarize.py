"""Summarize eval result files.

Example:
    .venv/bin/python -m evals.summarize evals/results/*.jsonl
"""

import collections
import json
import sys


def load(paths: list) -> list:
    rows = []
    for path in paths:
        with open(path) as handle:
            rows += [json.loads(line) for line in handle if line.strip()]
    return rows


def summarize(rows: list) -> None:
    groups = collections.defaultdict(list)
    for row in rows:
        groups[(row["model"], row["think"], row["arm"])].append(row)

    for (model, think, arm), group in groups.items():
        total = sum(r["passed"] for r in group)
        print(f"\n=== {model} | think {think} | arm {arm}: {total}/{len(group)} passed ({100 * total // len(group)}%) ===")
        for level in ("easy", "hard", "backend", "variant"):
            part = [r for r in group if r["level"] == level]
            if part:
                print(f"{level}: {sum(r['passed'] for r in part)}/{len(part)}")
        for task in dict.fromkeys(r["task"] for r in group):
            part = [r for r in group if r["task"] == task]
            print(
                f"  {task:22} {sum(r['passed'] for r in part):>2}/{len(part)}"
                f"  steps {sum(r['steps'] for r in part) / len(part):4.1f}"
                f"  secs {sum(r['seconds'] for r in part) / len(part):5.1f}"
                f"  denied {sum(r['denied'] for r in part):>2}"
                f"  bad-args {sum(r['bad_calls'] for r in part):>2}"
            )
        scored = [r["score"] for r in group if r.get("score") is not None]
        if scored:
            print(f"partial score on tasks with per-assertion checks: {100 * sum(scored) / len(scored):.0f}% ({len(scored)} runs)")
        calls = sum(r["tool_calls"] for r in group)
        print(
            f"tool calls {calls}, errors {sum(r['tool_errors'] for r in group)},"
            f" bad-argument {sum(r['bad_calls'] for r in group)}, denied {sum(r['denied'] for r in group)},"
            f" guard blocks {sum(r['guarded'] for r in group)}, length stops {sum(r.get('length_stops', 0) for r in group)}"
        )
        stops = collections.Counter(r["stop_reason"] for r in group)
        print(f"stop reasons {dict(stops)}; check errors {sum(1 for r in group if r.get('check_error'))}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m evals.summarize FILE [FILE ...]")
    summarize(load(sys.argv[1:]))
