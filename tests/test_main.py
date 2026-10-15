import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent
import main
import tools


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_run_agent = agent.run_agent
        self.histories = []  # a copy of the messages each run saw
        self.next_result = lambda messages: agent.AgentResult("ok", "done", 1)
        tools.confirm = lambda question: True

    def tearDown(self):
        agent.run_agent = self.original_run_agent
        tools.confirm = tools.ask_user
        tools.set_root(".")
        self.tmp.cleanup()

    def fake_run_agent(self, messages, *args, **kwargs):
        self.histories.append(list(messages))
        result = self.next_result(messages)
        if result.stop_reason == "done":
            messages.append({"role": "assistant", "content": result.reply})
        return result

    def run_main(self, *lines, argv=None):
        agent.run_agent = self.fake_run_agent
        script = iter(lines)

        def read_line(prompt):
            try:
                value = next(script)
            except StopIteration:
                raise EOFError from None
            if isinstance(value, BaseException):
                raise value
            return value

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main.main(argv or ["--root", self.tmp.name], read_line=read_line)
        return out.getvalue()

    def test_history_carries_across_prompts(self):
        self.run_main("first", "second")
        self.assertEqual(len(self.histories), 2)
        contents = [m["content"] for m in self.histories[1] if m["role"] != "system"]
        self.assertEqual(contents, ["first", "ok", "second"])

    def test_reset_clears_history(self):
        self.run_main("first", "/reset", "second")
        contents = [m["content"] for m in self.histories[1] if m["role"] != "system"]
        self.assertEqual(contents, ["second"])

    def read_during_run(self):
        Path(self.tmp.name, "a.txt").write_text("original")

        def run(messages):
            tools.read_file("a.txt")
            return agent.AgentResult("ok", "done", 1)

        self.next_result = run

    def test_reads_last_across_prompts(self):
        self.read_during_run()
        self.run_main("read it")
        self.assertNotIn("have not read it", tools.write_file("a.txt", "new"))

    def test_reset_forgets_which_files_were_read(self):
        self.read_during_run()
        self.run_main("read it", "/reset")
        self.assertIn("have not read it", tools.write_file("a.txt", "new"))

    def test_blank_lines_are_ignored(self):
        self.run_main("", "   ", "real")
        self.assertEqual(len(self.histories), 1)

    def test_exit_stops_the_loop(self):
        self.run_main("/exit", "never runs")
        self.assertEqual(self.histories, [])

    def test_end_of_input_stops_the_loop(self):
        self.run_main()
        self.assertEqual(self.histories, [])

    def test_failed_run_is_rolled_back(self):
        results = iter([agent.AgentResult("Error: no server", "error", 0)])
        self.next_result = lambda messages: next(results, agent.AgentResult("ok", "done", 1))
        self.run_main("will fail", "will work")
        contents = [m["content"] for m in self.histories[1] if m["role"] != "system"]
        self.assertEqual(contents, ["will work"])

    def test_interrupted_run_is_rolled_back(self):
        calls = iter([KeyboardInterrupt()])

        def maybe_interrupt(messages):
            error = next(calls, None)
            if error:
                messages.append({"role": "assistant", "content": "half done"})
                raise error
            return agent.AgentResult("ok", "done", 1)

        self.next_result = maybe_interrupt
        out = self.run_main("interrupted", "next")
        self.assertIn("Interrupted", out)
        contents = [m["content"] for m in self.histories[1] if m["role"] != "system"]
        self.assertEqual(contents, ["next"])

    def test_shows_reply_and_stop_reason(self):
        out = self.run_main("hi")
        self.assertIn("ok", out)
        self.assertIn("[done, 1 steps]", out)

    def test_root_option_sets_the_project_folder(self):
        self.run_main()
        self.assertEqual(tools.ROOT, Path(self.tmp.name).resolve())

    def test_bad_root_exits_with_a_message(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_main(argv=["--root", "/no/such/folder"])
        self.assertIn("not a folder", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
