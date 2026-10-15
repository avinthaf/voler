import argparse
import sys
from pathlib import Path

import agent
import tools

HELP = "Commands: /reset clears the conversation. /exit quits."


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A small coding agent.")
    parser.add_argument(
        "--root",
        default=".",
        help="Folder the agent may read and write. Defaults to the current folder.",
    )
    return parser.parse_args(argv)


def main(argv=None, read_line=input) -> None:
    args = parse_args(argv)
    if not Path(args.root).is_dir():
        sys.exit(f"Error: not a folder: {args.root}")
    tools.set_root(args.root)

    print(f"Model: {agent.MODEL}")
    print(f"Project folder: {tools.ROOT}")
    print(HELP)

    messages = agent.new_conversation()
    while True:
        try:
            line = read_line("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        if line in ("/exit", "/quit"):
            break
        if line == "/reset":
            messages = agent.new_conversation()
            tools.reset_session()
            print("Conversation cleared.")
            continue

        # Remember where this prompt starts. A failed or interrupted run rolls back to here.
        checkpoint = len(messages)
        messages.append({"role": "user", "content": line})
        try:
            result = agent.run_agent(messages)
        except (KeyboardInterrupt, EOFError):
            del messages[checkpoint:]
            print("\nInterrupted. That prompt was dropped from the history.")
            continue

        if result.stop_reason == "error":
            del messages[checkpoint:]
        print(f"\n{result.reply}\n[{result.stop_reason}, {result.steps} steps]")


if __name__ == "__main__":
    main()
