"""Run the eval tasks against a model. Writes one JSON line per run.

Example:
    .venv/bin/python -m evals.run --model ornith:9b --think off --arm C --runs 10
"""

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import ollama

import agent
import tools
from evals import policy
from evals.helpers import materialize
from evals.sandbox import sandbox_profile
from evals.tasks import TASKS, TASKS_BY_ID

RESULTS_DIR = Path(__file__).parent / "results"

# arm name: (tools the model gets, whether the read-before-write guard is on)
ARMS = {
    "A": ([tools.read_file, tools.bash, tools.write_file], False),
    "B": ([tools.read_file, tools.bash, tools.write_file], True),
    "C": ([tools.read_file, tools.bash, tools.write_file, tools.edit_file], True),
}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=agent.MODEL)
    parser.add_argument("--think", choices=["on", "off", "default"], default="off")
    parser.add_argument("--arm", choices=sorted(ARMS), default="C")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--start-run", type=int, default=1, help="First run number. Use it to resume an interrupted file.")
    parser.add_argument("--tasks", default="all", help='"all", "easy", "hard", "backend", "variant", or comma-separated task ids')
    parser.add_argument("--max-tokens", type=int, default=agent.MAX_RESPONSE_TOKENS)
    parser.add_argument("--num-ctx", type=int, default=agent.NUM_CTX)
    parser.add_argument("--out", help="Output file. Defaults to evals/results/<name>.jsonl")
    return parser.parse_args(argv)


def pick_tasks(spec: str) -> list:
    if spec == "all":
        # "variant" tasks are experiments. Ask for them by name.
        return [task for task in TASKS if task.level != "variant"]
    if spec in ("easy", "hard", "backend", "variant"):
        return [task for task in TASKS if task.level == spec]
    return [TASKS_BY_ID[task_id] for task_id in spec.split(",")]


def collect_files(root) -> dict:
    """Every text file in the folder, by relative path. Binary files are noted, not read."""
    found = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            name = str(path.relative_to(root))
            try:
                found[name] = path.read_text()
            except UnicodeDecodeError:
                found[name] = "<binary>"
    return found


def dump(message) -> dict:
    return message if isinstance(message, dict) else message.model_dump(exclude_none=True)


def run_one(task, arm_tools: list, chat_fn) -> dict:
    """Run one task in a fresh folder and return the result row."""
    with tempfile.TemporaryDirectory() as tmp:
        materialize(tmp, task.files)
        tools.set_root(tmp)
        messages = agent.new_conversation(arm_tools)
        messages.append({"role": "user", "content": task.prompt})

        started = time.time()
        with sandbox_profile(tmp) as profile, contextlib.redirect_stdout(io.StringIO()):
            tools.SANDBOX_PROFILE = profile
            try:
                result = agent.run_agent(messages, tools=arm_tools, chat_fn=chat_fn)
            finally:
                tools.SANDBOX_PROFILE = None
        seconds = time.time() - started

        check_error, detail = None, None
        try:
            if task.detail:
                detail = task.detail(Path(tmp), result.reply)
                passed = all(detail.values())
            else:
                passed = bool(task.check(Path(tmp), result.reply))
        except Exception as error:  # noqa: BLE001 - a broken check counts as a failure, and is recorded
            passed, check_error = False, repr(error)

        tool_msgs = [m for m in messages if isinstance(m, dict) and m["role"] == "tool"]
        called = [c.function.name for m in messages if not isinstance(m, dict) for c in (m.tool_calls or [])]
        return {
            "task": task.id,
            "level": task.level,
            "passed": passed,
            "check_detail": detail,
            "score": round(sum(detail.values()) / len(detail), 3) if detail else None,
            "check_error": check_error,
            "stop_reason": result.stop_reason,
            "steps": result.steps,
            "server_retries": result.server_retries,
            "tool_calls": len(tool_msgs),
            "tool_errors": sum(m["content"].startswith("Error:") for m in tool_msgs),
            "bad_calls": sum(m["content"].startswith("Error: bad call") for m in tool_msgs),
            "denied": sum("denied" in m["content"] for m in tool_msgs),
            "guarded": sum("have not read it" in m["content"] for m in tool_msgs),
            "edit_calls": called.count("edit_file"),
            "first_tool": called[0] if called else None,
            "thinking_msgs": sum(1 for m in messages if not isinstance(m, dict) and getattr(m, "thinking", None)),
            "seconds": round(seconds, 1),
            "reply": result.reply,
            "files": collect_files(tmp),
            "messages": [dump(m) for m in messages],
        }


def main(argv=None) -> None:
    args = parse_args(argv)
    # The model's shell and the checks should both use this project's Python, which has Flask.
    os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]
    arm_tools, guard = ARMS[args.arm]
    tasks = pick_tasks(args.tasks)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{args.model.replace(':', '-')}_think-{args.think}_arm-{args.arm}_{stamp}.jsonl"
    out = Path(args.out) if args.out else RESULTS_DIR / name
    out.parent.mkdir(parents=True, exist_ok=True)

    recorded = []
    context_used = []

    def recording_chat(**kwargs):
        response = ollama.chat(**kwargs)
        recorded.append(getattr(response, "done_reason", None))
        context_used.append((getattr(response, "prompt_eval_count", 0) or 0) + (getattr(response, "eval_count", 0) or 0))
        return response

    saved = (agent.MODEL, agent.THINK, agent.MAX_RESPONSE_TOKENS, agent.NUM_CTX, tools.confirm, tools.REQUIRE_READ_BEFORE_CHANGE)
    agent.NUM_CTX = args.num_ctx
    agent.MODEL = args.model
    agent.THINK = {"on": True, "off": False}.get(args.think)
    agent.MAX_RESPONSE_TOKENS = args.max_tokens
    tools.confirm = policy.approve
    tools.REQUIRE_READ_BEFORE_CHANGE = guard
    print(f"Writing to {out}")
    try:
        for run in range(args.start_run, args.runs + 1):
            for task in tasks:
                recorded.clear()
                context_used.clear()
                row = run_one(task, arm_tools, recording_chat)
                row.update(
                    model=args.model, think=args.think, arm=args.arm, run=run,
                    max_tokens=args.max_tokens, num_ctx=args.num_ctx,
                    length_stops=recorded.count("length"),
                    max_context_used=max(context_used, default=0),
                )
                with open(out, "a") as handle:
                    handle.write(json.dumps(row, default=str) + "\n")
                print(f"run {run} {task.id}: {'PASS' if row['passed'] else 'fail'} ({row['seconds']}s)", flush=True)
    finally:
        (agent.MODEL, agent.THINK, agent.MAX_RESPONSE_TOKENS, agent.NUM_CTX,
         tools.confirm, tools.REQUIRE_READ_BEFORE_CHANGE) = saved


if __name__ == "__main__":
    main()
