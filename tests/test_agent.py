import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ollama import ChatResponse, Message, ResponseError

import agent
import tools


def reply(content: str) -> ChatResponse:
    return ChatResponse(message=Message(role="assistant", content=content))


def call_tools(*calls) -> ChatResponse:
    """Build a response that asks for tools. Each call is (name, arguments)."""
    tool_calls = [
        Message.ToolCall(function=Message.ToolCall.Function(name=name, arguments=args))
        for name, args in calls
    ]
    return ChatResponse(message=Message(role="assistant", tool_calls=tool_calls))


class FakeChat:
    """Stands in for ollama.chat. Returns scripted responses, then repeats the last."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []
        self.kwargs = []

    def __call__(self, **kwargs):
        self.seen.append(len(kwargs["messages"]))
        self.kwargs.append(kwargs)
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tools.set_root(self.tmp.name)
        tools.confirm = lambda question: True
        Path(self.tmp.name, "a.txt").write_text("file contents")

    def tearDown(self):
        tools.confirm = tools.ask_user
        self.tmp.cleanup()

    def run_agent(self, fake):
        messages = agent.new_conversation()
        messages.append({"role": "user", "content": "do the task"})
        with contextlib.redirect_stdout(io.StringIO()):
            result = agent.run_agent(messages, chat_fn=fake)
        return result, messages

    def tool_messages(self, messages):
        return [m for m in messages if isinstance(m, dict) and m["role"] == "tool"]

    def test_plain_reply_ends_the_task(self):
        result, _ = self.run_agent(FakeChat(reply("all done")))
        self.assertEqual((result.reply, result.stop_reason, result.steps), ("all done", "done", 1))

    def test_tool_result_goes_back_to_the_model(self):
        fake = FakeChat(call_tools(("read_file", {"path": "a.txt"})), reply("it says file contents"))
        result, messages = self.run_agent(fake)
        self.assertEqual(result.stop_reason, "done")
        self.assertEqual(result.steps, 2)
        tool_msgs = self.tool_messages(messages)
        self.assertEqual(tool_msgs[0]["content"], "file contents")
        self.assertEqual(tool_msgs[0]["tool_name"], "read_file")

    def test_parallel_calls_each_get_a_result(self):
        fake = FakeChat(
            call_tools(("read_file", {"path": "a.txt"}), ("read_file", {"path": "missing.txt"})),
            reply("done"),
        )
        _, messages = self.run_agent(fake)
        results = [m["content"] for m in self.tool_messages(messages)]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], "file contents")
        self.assertTrue(results[1].startswith("Error: file not found"))

    def test_unknown_tool_returns_error_text(self):
        fake = FakeChat(call_tools(("delete_file", {"path": "a.txt"})), reply("ok"))
        _, messages = self.run_agent(fake)
        content = self.tool_messages(messages)[0]["content"]
        self.assertIn("no tool named delete_file", content)
        self.assertIn("write_file", content)

    def test_write_file_changes_the_file(self):
        fake = FakeChat(
            call_tools(("write_file", {"path": "new.py", "content": "print('hi')\n"})),
            reply("done"),
        )
        result, _ = self.run_agent(fake)
        self.assertEqual(result.stop_reason, "done")
        self.assertEqual(Path(self.tmp.name, "new.py").read_text(), "print('hi')\n")

    def test_denied_write_reaches_the_model_and_leaves_no_file(self):
        tools.confirm = lambda question: False
        fake = FakeChat(call_tools(("write_file", {"path": "new.py", "content": "x"})), reply("ok"))
        _, messages = self.run_agent(fake)
        self.assertIn("denied", self.tool_messages(messages)[0]["content"])
        self.assertFalse(Path(self.tmp.name, "new.py").exists())

    def test_bad_arguments_return_error_text(self):
        fake = FakeChat(call_tools(("read_file", {"wrong_name": "a.txt"})), reply("ok"))
        _, messages = self.run_agent(fake)
        self.assertIn("bad call to read_file", self.tool_messages(messages)[0]["content"])

    def test_identical_calls_three_times_stops(self):
        same = call_tools(("read_file", {"path": "a.txt"}))
        result, messages = self.run_agent(FakeChat(same))
        self.assertEqual(result.stop_reason, "repeat")
        self.assertEqual(result.steps, 3)
        results = [m["content"] for m in self.tool_messages(messages)]
        self.assertEqual(results[:2], ["file contents", "file contents"])
        self.assertIn("3 times in a row", results[2])

    def test_different_arguments_are_not_a_repeat(self):
        fake = FakeChat(
            call_tools(("read_file", {"path": "a.txt"})),
            call_tools(("read_file", {"path": "b.txt"})),
            call_tools(("read_file", {"path": "a.txt"})),
            reply("done"),
        )
        result, _ = self.run_agent(fake)
        self.assertEqual(result.stop_reason, "done")

    def test_too_many_calls_in_one_response_are_cut_off(self):
        many = call_tools(*[("read_file", {"path": f"f{i}.txt"}) for i in range(20)])
        result, messages = self.run_agent(FakeChat(many, reply("done")))
        results = [m["content"] for m in self.tool_messages(messages)]
        self.assertEqual(len(results), agent.MAX_CALLS_PER_STEP)
        self.assertIn("you made 20 calls at once", results[-1])
        self.assertNotIn("calls at once", results[0])
        self.assertEqual(result.stop_reason, "done")

    def test_prompt_mentions_edit_file_only_when_it_is_available(self):
        with_edit = agent.system_prompt([tools.read_file, tools.edit_file])
        without = agent.system_prompt([tools.read_file, tools.write_file])
        self.assertIn("edit_file", with_edit)
        self.assertNotIn("edit_file", without)

    def test_think_setting_is_passed_only_when_set(self):
        for value, expected in ((None, False), (True, True), (False, True)):
            agent.THINK = value
            try:
                fake = FakeChat(reply("done"))
                self.run_agent(fake)
            finally:
                agent.THINK = None
            self.assertEqual("think" in fake.kwargs[0], expected)
            if value is not None:
                self.assertEqual(fake.kwargs[0]["think"], value)

    def test_prompt_tells_the_model_where_it_works(self):
        prompt = agent.system_prompt(agent.DEFAULT_TOOLS)
        self.assertIn("relative paths", prompt)
        self.assertIn("Never use absolute paths", prompt)
        self.assertIn("If a command is denied, do not retry it", prompt)

    def test_denied_messages_tell_the_model_not_to_retry(self):
        tools.confirm = lambda question: False
        Path(self.tmp.name, "a.txt").write_text("x")
        tools.read_file("a.txt")
        fake = FakeChat(
            call_tools(
                ("bash", {"command": "ls"}),
                ("write_file", {"path": "n.txt", "content": "x"}),
                ("edit_file", {"path": "a.txt", "old": "x", "new": "y"}),
            ),
            reply("ok"),
        )
        _, messages = self.run_agent(fake)
        for content in [m["content"] for m in self.tool_messages(messages)]:
            self.assertIn("denied", content)
            self.assertIn("Do not retry it", content)

    def test_repeat_stop_gives_the_model_a_last_turn_without_tools(self):
        same = call_tools(("read_file", {"path": "a.txt"}))
        fake = FakeChat(same, same, same, reply("I read a.txt three times and found nothing new."))
        result, messages = self.run_agent(fake)
        self.assertEqual(result.stop_reason, "repeat")
        self.assertEqual(result.reply, "I read a.txt three times and found nothing new.")
        self.assertNotIn("tools", fake.kwargs[-1])
        self.assertIn("tools", fake.kwargs[0])
        self.assertEqual(messages[-2], {"role": "user", "content": agent.WRAP_UP_PROMPT})

    def test_wrap_up_falls_back_when_the_model_still_asks_for_tools(self):
        same = call_tools(("read_file", {"path": "a.txt"}))
        result, _ = self.run_agent(FakeChat(same))
        self.assertEqual(result.reply, agent.STOP_MESSAGES["repeat"])

    def test_step_cap_also_gets_a_wrap_up(self):
        counter = iter(range(1000))
        wrap_up = reply("I ran out of steps.")

        def endless(**kwargs):
            if "tools" not in kwargs:
                return wrap_up
            return call_tools(("read_file", {"path": f"file{next(counter)}.txt"}))

        result, _ = self.run_agent(endless)
        self.assertEqual(result.stop_reason, "max_steps")
        self.assertEqual(result.reply, "I ran out of steps.")

    def test_a_normal_finish_has_no_wrap_up(self):
        fake = FakeChat(reply("hi"))
        self.run_agent(fake)
        self.assertEqual(len(fake.kwargs), 1)

    def test_bash_commands_that_differ_only_in_spacing_count_as_repeats(self):
        fake = FakeChat(
            call_tools(("bash", {"command": "ls  -la 2>/dev/null"})),
            call_tools(("bash", {"command": "ls -la"})),
            call_tools(("bash", {"command": "ls   -la  2>&1"})),
            reply("stuck"),
        )
        result, _ = self.run_agent(fake)
        self.assertEqual(result.stop_reason, "repeat")
        self.assertEqual(result.steps, 3)

    def test_different_write_content_is_never_a_repeat(self):
        calls = [call_tools(("write_file", {"path": "n.txt", "content": f"a  {i}"})) for i in range(3)]
        result, _ = self.run_agent(FakeChat(*calls, reply("done")))
        self.assertEqual(result.stop_reason, "done")

    def test_four_denials_in_a_row_stop_the_run(self):
        tools.confirm = lambda question: False
        fake = FakeChat(
            *[call_tools(("bash", {"command": f"ls dir{i}"})) for i in range(4)],
            reply("I could not list anything."),
        )
        result, _ = self.run_agent(fake)
        self.assertEqual(result.stop_reason, "denied")
        self.assertEqual(result.steps, agent.DENIAL_STREAK_LIMIT)
        self.assertEqual(result.reply, "I could not list anything.")

    def test_a_success_resets_the_denial_streak(self):
        tools.confirm = lambda question: "ok" in question
        commands = ["ls no1", "ls no2", "ls no3", "echo ok", "ls no4", "ls no5", "ls no6"]
        fake = FakeChat(*[call_tools(("bash", {"command": c})) for c in commands], reply("done"))
        result, _ = self.run_agent(fake)
        self.assertEqual(result.stop_reason, "done")

    def scripted(self, *outcomes):
        """A chat function that raises or returns each outcome in turn."""
        remaining = list(outcomes)
        self.chat_calls = []

        def chat(**kwargs):
            self.chat_calls.append(kwargs)
            outcome = remaining.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return chat

    BAD_TOOL_CALL = ResponseError(
        'llama-server returned invalid tool call arguments for "write_file": unexpected end of JSON input', 500
    )

    def test_a_malformed_tool_call_is_retried_once_without_a_nudge(self):
        chat = self.scripted(self.BAD_TOOL_CALL, reply("fine"))
        result, messages = self.run_agent(chat)
        self.assertEqual((result.stop_reason, result.server_retries), ("done", 1))
        self.assertFalse(any(isinstance(m, dict) and m["content"] == agent.MALFORMED_NUDGE for m in messages))

    def test_a_second_malformed_tool_call_adds_a_nudge(self):
        chat = self.scripted(self.BAD_TOOL_CALL, self.BAD_TOOL_CALL, reply("fine"))
        result, messages = self.run_agent(chat)
        self.assertEqual((result.stop_reason, result.server_retries), ("done", 2))
        nudges = [m for m in messages if isinstance(m, dict) and m["content"] == agent.MALFORMED_NUDGE]
        self.assertEqual(len(nudges), 1)

    def test_retries_stop_after_the_limit(self):
        chat = self.scripted(*[self.BAD_TOOL_CALL] * (agent.MAX_MALFORMED_RETRIES + 1))
        result, _ = self.run_agent(chat)
        self.assertEqual(result.stop_reason, "error")
        self.assertEqual(result.server_retries, agent.MAX_MALFORMED_RETRIES)
        self.assertIn("invalid tool call arguments", result.reply)

    def test_other_server_errors_are_not_retried(self):
        chat = self.scripted(ResponseError("model 'nope' not found", 404))
        result, _ = self.run_agent(chat)
        self.assertEqual((result.stop_reason, result.server_retries), ("error", 0))
        self.assertEqual(len(self.chat_calls), 1)

    def test_a_retry_does_not_use_up_a_step(self):
        chat = self.scripted(self.BAD_TOOL_CALL, reply("fine"))
        result, _ = self.run_agent(chat)
        self.assertEqual(result.steps, 1)

    def cut_off(self, text=""):
        return ChatResponse(message=Message(role="assistant", content=text), done_reason="length")

    def test_a_reply_cut_off_by_a_limit_is_not_a_finished_task(self):
        chat = self.scripted(self.cut_off("I will write the"), reply("All done."))
        result, messages = self.run_agent(chat)
        self.assertEqual((result.stop_reason, result.reply), ("done", "All done."))
        self.assertTrue(any(isinstance(m, dict) and m["content"] == agent.TRUNCATED_NUDGE for m in messages))

    def test_a_cut_off_reply_keeps_the_partial_message_in_the_history(self):
        chat = self.scripted(self.cut_off("partial text"), reply("ok"))
        _, messages = self.run_agent(chat)
        contents = [m["content"] if isinstance(m, dict) else m.content for m in messages]
        self.assertIn("partial text", contents)

    def test_repeated_cut_offs_end_the_run_as_truncated(self):
        chat = self.scripted(*[self.cut_off("part")] * (agent.MAX_TRUNCATION_RETRIES + 1))
        result, _ = self.run_agent(chat)
        self.assertEqual(result.stop_reason, "truncated")
        self.assertEqual(result.reply, "part")

    def test_a_normal_stop_is_not_treated_as_a_cut_off(self):
        chat = self.scripted(ChatResponse(message=Message(role="assistant", content="fine"), done_reason="stop"))
        result, _ = self.run_agent(chat)
        self.assertEqual(result.stop_reason, "done")
        self.assertEqual(len(self.chat_calls), 1)

    def test_the_context_window_is_large_enough_for_long_runs(self):
        self.assertGreaterEqual(agent.NUM_CTX, 32768)
        self.assertGreaterEqual(agent.NUM_CTX, agent.MAX_RESPONSE_TOKENS * 2)

    def test_step_cap(self):
        counter = iter(range(1000))

        def endless(**kwargs):
            return call_tools(("read_file", {"path": f"file{next(counter)}.txt"}))

        result, _ = self.run_agent(endless)
        self.assertEqual(result.stop_reason, "max_steps")
        self.assertEqual(result.steps, agent.MAX_STEPS)

    def test_ollama_not_running(self):
        def broken(**kwargs):
            raise ConnectionError("no server")

        result, _ = self.run_agent(broken)
        self.assertEqual(result.stop_reason, "error")
        self.assertIn("Is it running", result.reply)


if __name__ == "__main__":
    unittest.main()
