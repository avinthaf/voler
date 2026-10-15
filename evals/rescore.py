"""Re-run today's checks on saved results, without running any model.

Use it after fixing or tightening a check. The original files are never changed.

Example:
    .venv/bin/python -m evals.rescore evals/results/some_file.jsonl --task b1_flask_todo_api
    .venv/bin/python -m evals.rescore evals/results/*.jsonl --task b1_flask_todo_api --write
"""

import argparse
import collections
import json
import tempfile
from pathlib import Path

from evals.helpers import materialize
from evals.tasks import TASKS_BY_ID


def rescore_row(row: dict) -> dict:
    """Return a copy of the row, scored with the current check."""
    task = TASKS_BY_ID.get(row["task"])
    if task is None:
        return row
    with tempfile.TemporaryDirectory() as tmp:
        saved = {name: text for name, text in row["files"].items() if text != "<binary>"}
        materialize(tmp, saved)
        if task.detail:
            detail = task.detail(Path(tmp), row["reply"])
            passed = all(detail.values())
        else:
            detail, passed = None, bool(task.check(Path(tmp), row["reply"]))
    new = dict(row)
    new["passed_original"] = row["passed"]
    new["passed"] = passed
    new["check_detail"] = detail
    new["score"] = round(sum(detail.values()) / len(detail), 3) if detail else None
    return new


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+")
    parser.add_argument("--task", action="append", help="Only rescore this task id. Can be repeated.")
    parser.add_argument("--write", action="store_true", help="Save <file>.rescored.jsonl next to each input")
    args = parser.parse_args(argv)

    for path in args.files:
        rows = [json.loads(line) for line in open(path) if line.strip()]
        rows = [r for r in rows if not args.task or r["task"] in args.task]
        if not rows:
            continue
        rescored = [rescore_row(r) for r in rows]
        print(f"\n=== {Path(path).name} ===")
        by_task = collections.defaultdict(list)
        for old, new in zip(rows, rescored):
            by_task[old["task"]].append((old, new))
        for task_id, pairs in by_task.items():
            before = sum(o["passed"] for o, _ in pairs)
            after = sum(n["passed"] for _, n in pairs)
            scores = [n["score"] for _, n in pairs if n.get("score") is not None]
            extra = f"  partial score {100 * sum(scores) / len(scores):.0f}%" if scores else ""
            print(f"  {task_id:28} before {before}/{len(pairs)}  after {after}/{len(pairs)}{extra}")
        if args.write:
            out = Path(path).with_suffix(".rescored.jsonl")
            out.write_text("".join(json.dumps(r, default=str) + "\n" for r in rescored))
            print(f"  wrote {out}")


if __name__ == "__main__":
    main()
