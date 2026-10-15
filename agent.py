import json
import re
from dataclasses import dataclass

from ollama import ResponseError, chat

from tools import bash, edit_file, read_file, write_file

MODEL = "ornith-1.5:9b"
NUM_CTX = 32768  # prompt, history, thinking, and the reply all share this window
MAX_STEPS = 25
REPEAT_LIMIT = 3
DENIAL_STREAK_LIMIT = 4
MAX_CALLS_PER_STEP = 5
MAX_MALFORMED_RETRIES = 2
MAX_TRUNCATION_RETRIES = 2
MAX_RESPONSE_TOKENS = 16384  # thinking tokens count toward this
THINK = True  # None keeps the model default. True or False turns thinking on or off.
DISPLAY_CHARS = 500

DEFAULT_TOOLS = [read_file, bash, write_file, edit_file]

_CHANGE_WITH_WRITE = "To change a file, read it, then write the full new contents with write_file. "
_CHANGE_WITH_EDIT = (
    "To change part of a file, read it, then use edit_file. "
    "To create a file or replace it all, use write_file. "
)

WRAP_UP_PROMPT = (
    "Stop now. Do not call any tools. "
    "In a few sentences, say what you found, what you changed, and what is still unfinished."
)

STOP_MESSAGES = {
    "truncated": "Stopped: the model's reply kept getting cut off.",
    "repeat": "Stopped: the model kept repeating the same call.",
    "denied": "Stopped: too many denied commands in a row.",
    "max_steps": "Stopped: reached the step limit.",
}

MALFORMED_NUDGE = (
    "Your last tool call was rejected because its arguments were not valid JSON. "
    "Try again. If you are writing a long file, write it in smaller pieces."
)

TRUNCATED_NUDGE = (
    "Your last reply was cut off because it was too long. Continue where you left off. "
    "Keep your thinking short, and write long files in smaller pieces."
)

_STDERR_REDIRECTS = re.compile(r"\s*2>\s*(/dev/null|&1)")


def system_prompt(tools: list) -> str:
    """Build the system prompt. The wording about changing files depends on the tools."""
    has_edit = any(tool.__name__ == "edit_file" for tool in tools)
    return (
        "You are a coding agent working in a project folder. "
        "Use your tools to read files, write files, and run shell commands. "
        "Your shell starts in the project folder. "
        "Use relative paths such as notes.txt or src/app.py. "
        "Never use absolute paths, and never leave the folder. "
        + (_CHANGE_WITH_EDIT if has_edit else _CHANGE_WITH_WRITE)
        + "You can call several tools in a row. "
        "Never guess what a file contains. Read it first. "
        "If a command is denied, do not retry it. Try another way, or say what you could not do. "
        "When the task is done, reply with a short plain answer and call no tools."
    )


@dataclass
class AgentResult:
    reply: str
    stop_reason: str  # "done", "max_steps", "repeat", "denied", "truncated", or "error"
    steps: int
    server_retries: int = 0  # times Ollama rejected a malformed tool call and we asked again


def new_conversation(tools: list = DEFAULT_TOOLS) -> list:
    return [{"role": "system", "content": system_prompt(tools)}]


def _signature(call) -> str:
    """A string that is equal for calls with the same name and arguments.

    Bash commands that differ only in spacing or stderr redirects count as the same.
    """
    args = dict(call.function.arguments or {})
    if call.function.name == "bash" and isinstance(args.get("command"), str):
        args["command"] = " ".join(_STDERR_REDIRECTS.sub(" ", args["command"]).split())
    return json.dumps({"name": call.function.name, "args": args}, sort_keys=True, default=str)


def _run_tool(call, tools_by_name: dict) -> str:
    name = call.function.name
    func = tools_by_name.get(name)
    if func is None:
        return f"Error: no tool named {name}. Available tools: {', '.join(tools_by_name)}"
    try:
        return str(func(**(call.function.arguments or {})))
    except Exception as e:  # noqa: BLE001 - any tool failure goes back to the model as text
        return f"Error: bad call to {name}: {e}"


def _show(text: str) -> None:
    if len(text) > DISPLAY_CHARS:
        text = text[:DISPLAY_CHARS] + "... [display truncated]"
    print("    " + text.replace("\n", "\n    "))


def _chat(chat_fn, messages: list, tools: list | None):
    extra = {} if THINK is None else {"think": THINK}
    if tools is not None:
        extra["tools"] = tools
    return chat_fn(
        model=MODEL,
        messages=messages,
        options={"num_ctx": NUM_CTX, "num_predict": MAX_RESPONSE_TOKENS},
        **extra,
    )


def _is_malformed_tool_call(error: ResponseError) -> bool:
    """Ollama refuses a reply whose tool call arguments are not valid JSON. That is worth another try."""
    return "invalid tool call arguments" in str(error)


def _wrap_up(messages: list, chat_fn, reason: str, steps: int) -> AgentResult:
    """A guard stopped the run. Give the model one last turn, with no tools, to say where it got to."""
    fallback = STOP_MESSAGES[reason]
    messages.append({"role": "user", "content": WRAP_UP_PROMPT})
    try:
        response = _chat(chat_fn, messages, tools=None)
    except (ConnectionError, ResponseError):
        return AgentResult(fallback, reason, steps)
    messages.append(response.message)
    return AgentResult((response.message.content or "").strip() or fallback, reason, steps)


def run_agent(messages: list, tools: list = DEFAULT_TOOLS, chat_fn=chat) -> AgentResult:
    """Run one task. Appends every message to `messages` as it goes."""
    tools_by_name = {tool.__name__: tool for tool in tools}
    recent = []
    denied_streak = 0
    retries = 0
    truncations = 0

    def finish(result: AgentResult) -> AgentResult:
        result.server_retries = retries
        return result

    for step in range(1, MAX_STEPS + 1):
        for attempt in range(MAX_MALFORMED_RETRIES + 1):
            try:
                response = _chat(chat_fn, messages, tools)
                break
            except ConnectionError:
                reply = "Error: cannot reach Ollama. Is it running? Try `ollama serve`."
                return finish(AgentResult(reply, "error", step - 1))
            except ResponseError as e:
                if _is_malformed_tool_call(e) and attempt < MAX_MALFORMED_RETRIES:
                    retries += 1
                    if attempt >= 1:  # a plain second try first, then a nudge
                        messages.append({"role": "user", "content": MALFORMED_NUDGE})
                    continue
                return finish(AgentResult(f"Error from Ollama: {e}", "error", step - 1))

        message = response.message
        messages.append(message)

        if not message.tool_calls:
            if getattr(response, "done_reason", None) == "length":
                # The reply hit a limit. It is not a finished answer.
                truncations += 1
                if truncations > MAX_TRUNCATION_RETRIES:
                    return finish(AgentResult(message.content or STOP_MESSAGES["truncated"], "truncated", step))
                messages.append({"role": "user", "content": TRUNCATED_NUDGE})
                continue
            return finish(AgentResult(message.content or "", "done", step))

        calls = message.tool_calls
        note = ""
        if len(calls) > MAX_CALLS_PER_STEP:
            note = f"\nNote: you made {len(calls)} calls at once. Only the first {MAX_CALLS_PER_STEP} ran."
            calls = calls[:MAX_CALLS_PER_STEP]
            message.tool_calls = calls

        stuck = False
        for index, call in enumerate(calls):
            name = call.function.name
            print(f"[step {step}] {name}({json.dumps(call.function.arguments, default=str)})")

            recent.append(_signature(call))
            if stuck or recent[-REPEAT_LIMIT:] == [recent[-1]] * REPEAT_LIMIT:
                stuck = True
                result = f"Error: you made this exact call {REPEAT_LIMIT} times in a row. Stopped."
            else:
                result = _run_tool(call, tools_by_name)

            denied_streak = denied_streak + 1 if result.startswith("Error: the user denied") else 0
            if note and index == len(calls) - 1:
                result += note
            _show(result)
            messages.append({"role": "tool", "tool_name": name, "content": result})

        if stuck:
            return finish(_wrap_up(messages, chat_fn, "repeat", step))
        if denied_streak >= DENIAL_STREAK_LIMIT:
            return finish(_wrap_up(messages, chat_fn, "denied", step))

    return finish(_wrap_up(messages, chat_fn, "max_steps", MAX_STEPS))
