# Plan: Coding agent harness

Goal: a small agent harness that helps with coding. It runs on a small local model.

This plan grows one section at a time. Sections are marked as agreed or draft.

## Phases

**Phase I (current): raw capabilities.** Build the harness. Test what the small model can do with plain tools and no retrieval.

**Phase II (parked): required retrieval.** See the last section of this file.

## 1. Capabilities and model (agreed)

**Model: `llama3.2:3b`.** The tag is pinned. It is a local alias of `llama3.2:latest`, made with `ollama cp`. We keep a small model on purpose. The experiment is to see how a 3B model performs as a coding agent.

**Switched from `llama3.2:1b` after the first benchmark.** The 3B model passed 63% of runs. The 1B model passed 27%. See the Phase I results log.

**Default model is now `ornith:9b`, thinking off.** It scored 93% to 97% on the first benchmark, with no malformed tool calls. Thinking showed no clear gain and cost about 40% more time. The Llama models stay available for the small-model comparison.

**Expect weak spots.** Small models often pick the wrong tool or send bad arguments. The harness must handle this, not hide it.

**Tool calling: core.** The agent can't change code without it.

**Structured outputs: later.** Useful for plans or fixed-format replies. Not needed for version one.

**Thinking: skip.** llama3.2 has no thinking mode.

**Streaming: optional, last.** It is a transport feature, not model-specific. It only makes replies appear as they are generated.

**Doc quirks to avoid:**

- Tool `content` must be a string. Wrap results in `str()`.
- Parameter descriptions must sit inside one docstring. Otherwise the schema misses them.

## 2. Tools (agreed)

**Keep the tool list tiny.** Small models get confused by many tools. Start with three.

**Version one tools:**

- `bash(command)`: runs a shell command and returns its output.
- `read_file(path)`: returns a file's contents.
- `write_file(path, content)`: creates or overwrites a file.

**Stretch tool: `edit_file(path, old, new)`.** It swaps one exact string for another. Small models often get the exact match wrong, so we add it only after the first three work.

**Every tool takes plain string arguments.** No nested objects or optional fields. Simple schemas are easier for a small model.

**Every tool returns a string.** Errors come back as text, like `"Error: file not found"`. The model can then read the error and retry.

**Safety rails:**

- Confine paths to the project folder.
- Time out bash after 30 seconds.
- Truncate long output so it doesn't flood the context.
- Ask the user to confirm before `bash` and `write_file` run.

**Where it lives:** a `tools.py` file. Each tool is a plain function with a full docstring. The SDK builds the schema from it.

## 3. Agent loop (agreed)

**The core is a loop.** Call the model, run any requested tools, repeat. Stop when a reply has no `tool_calls`.

**Each turn:**

1. Send the full message history and the tool list to `chat`.
2. Append the assistant message to the history.
3. If there are no `tool_calls`, print the reply and stop.
4. Otherwise run every tool call and append one `role: "tool"` message per call.

**Start with a system prompt.** It tells the model it is a coding agent. It says it can call several tools in a row and should stop when done.

**Guard against small-model mistakes:**

- Unknown tool name: return `"Error: no tool named X"`.
- Bad arguments: catch the exception and return it as text.
- Cap each task at 25 steps so it can't loop forever. A step is one model call, which may request several tools. Keep it as a constant so it is easy to change.
- Stop if the model makes the same call three times in a row. "Same" means the same tool name and the same arguments. Different arguments count as a different call.
- The step cap is the backstop for a model that keeps varying its arguments.

**Make it visible.** Print every tool call and its result as it happens. This is how you see where the small model fails.

**Two loops, not one.** An outer loop reads your prompts and keeps the history. The inner loop is the agent turn above.

**Where it lives:** `agent.py` holds the loop. `main.py` becomes the entry point that runs it.

## 4. Structured outputs and testing (agreed)

**Structured outputs are optional in version one.** The loop works without them. We add them as an experiment.

**Experiment: a planning step.** Before the loop, ask the model for a plan as JSON. Use a Pydantic model with a list of short step strings. Pass its schema to `format`.

**Why it may help a small model.** The `format` parameter constrains the output to a schema. The model can't ramble or break the JSON.

**Keep it in a separate call.** The docs don't say whether `format` and `tools` work together in one request. A plan call with no tools avoids the question.

**Then compare.** Run the same tasks with and without the planning step. This shows whether structure helps a small model.

**Testing: a small task set.** Each task has a starting folder and a check that passes or fails. Examples:

- Create `hello.py` that prints "hello".
- Fix a bug in a one-function file.
- Rename a function across two files.
- Run a test file and fix the failure.

**Log every run.** Save each transcript as a JSONL file: messages, tool calls, results, and step count.

**Measure three things:**

- Task pass rate.
- Share of tool calls with a valid name and arguments.
- Steps used per task.

**Where it lives:** `plan.py` for the planning step. An `evals/` folder for tasks and the runner.

## 5. Build order and open risks (agreed)

**Build in small steps.** Test each one before moving on.

1. `tools.py`: write the three tools. Test each by hand, with no model. **Done.** Tests live in `tests/test_tools.py`. Run them with `.venv/bin/python -m unittest tests.test_tools`.
2. `agent.py`: build the loop with `read_file` and `bash` only. Try it on `llama3.2:1b`. **Done.** Loop tests are in `tests/test_agent.py`. First real run, one attempt per task: 1 of 3 correct. Failure modes seen: a tool call that echoed the schema as arguments, a partial answer, and an invented answer after a failed call ("23 lines" for a 4-line file).
3. Add `write_file`, the safety rails, and the confirmation prompts. **Done.** The safety rails and prompts were already in `tools.py`. This step added `write_file` to the agent and its tests. First write trial, one attempt per task: 0 of 3 correct. Failure modes seen: malformed arguments on 2 of 3 calls, a file overwritten with garbage (`add(a, b)`), and a reply claiming the fix worked when it hadn't.
4. `main.py`: the outer loop that reads your prompts. **Done.** Run it with `.venv/bin/python main.py --root <folder>`. Commands: `/reset` and `/exit`. Tests are in `tests/test_main.py`.
5. Logging: save every run as JSONL.
6. `evals/`: the task set and the runner. Record a baseline pass rate. **Done.** Run with `.venv/bin/python -m evals.run`. Summarize with `.venv/bin/python -m evals.summarize evals/results/*.jsonl`. Results are git-ignored. Tests are in `tests/test_evals.py`.
7. `plan.py`: the planning experiment. Compare against the baseline.
8. Optional: streaming, then `edit_file`.

**Open risks:**

- **Context window.** Ollama's default context is small. Long runs may silently drop early messages. Set `num_ctx` in `options`.
- **Model size.** Even at 3B, expect frequent bad tool calls and failed edits. Low pass rates are a result, not a bug. Keep the model name in one constant so swapping models is a one-line change.
- **Tool calls as plain text.** Small models sometimes print a tool call as text instead of making one. Log these as failures.
- **Safety.** Bash can delete files. Confirmation prompts and path limits stay on, even in evals. Run evals in throwaway folders.
- **Ollama must be running.** The harness should fail with a clear message if it isn't.

**Done means:** the agent completes at least one eval task end to end, and the logs show what it did.

## Phase I results log

**First benchmark: 6 tasks, 10 runs each, on `llama3.2` (3B) and `llama3.2:1b`.**

Tasks: read a file, list Python files, count lines, create a file, fix a bug, rename a function. Bash was limited to read-only commands. Writes were confined to a throwaway folder.

| Task | 3B | 1B |
|---|---|---|
| Read a file and report it | 10/10 | 7/10 |
| List Python files | 8/10 | 0/10 |
| Count lines | 7/10 | 6/10 |
| Create a file | 3/10 | 2/10 |
| Fix a bug | 10/10 | 1/10 |
| Rename a function | 0/10 | 0/10 |
| **Total** | **38/60 (63%)** | **16/60 (27%)** |

**Tool calls with errors:** 3B 29%, 1B 73%. **Calls with bad arguments:** 3B 24%, 1B 58%.

**Every failed run ended with the model replying as if done.** None hit the step cap. The model never noticed it had failed.

**Harness changes made during this work:**

- Per-response cap of 5 tool calls. A 1B run produced 1,762 calls in one response and took 20 minutes.
- Cap of 4,096 tokens per model response.

**Caveats:**

- 10 runs per task is a small sample.
- The 3B model is quantized at Q4_K_M. The 1B model is Q8_0.
- Checks are static. Model-written code was not run.
- An earlier pass had a too-strict bash filter and loose file checks. Its numbers were discarded.

**Where the scripts are:** the session scratchpad. They move to `evals/` in step 6.

## Experiment: read-before-write guard and `edit_file`

**Setup.** The 3B model, 7 tasks, 10 runs each, three configurations. One new task, `w4`, changes a tax rate in a file the model can't guess.

- **A, baseline:** read, bash, write tools. No guard.
- **B, guard:** same tools. Writes to an unread existing file are blocked.
- **C, guard and `edit_file`:** adds `edit_file(path, old, new)`.

| Task | A | B | C |
|---|---|---|---|
| Read a file | 10/10 | 10/10 | 10/10 |
| List Python files | 9/10 | 8/10 | 5/10 |
| Count lines | 4/10 | 3/10 | 5/10 |
| Create a file | 2/10 | 4/10 | 1/10 |
| Fix a bug | 10/10 | 7/10 | 1/10 |
| Rename a function | 0/10 | 0/10 | 0/10 |
| Change a value in an unseen file | 0/10 | 1/10 | 4/10 |
| **Total** | **35/70 (50%)** | **33/70 (47%)** | **26/70 (37%)** |

**Findings:**

- **The guard works as designed.** After a block, the model read the file in 26 of 26 runs (B) and 22 of 22 (C).
- **Reading was not the bottleneck.** Only 7 of 26 (B) and 5 of 22 (C) of those runs passed.
- **Argument mix-ups dominate.** Bad-argument calls rose from 21 (A) to 69 (B) and 68 (C). `read_file` was called without `path` 77 times in B. In C, `write_file` got `old` or `new` 13 times, and `edit_file` got `content` 7 times.
- **`edit_file` helps when the call is right.** The unseen-file task went from 0/10 to 4/10.
- **The earlier "bug fix 10/10" was misleading.** The model rewrote the file from the task description. It never needed to read it.
- **More tools hurt unrelated tasks.** Listing files fell from 9/10 to 5/10 in C.
- **Noise is large.** Config A scored 7/10 on counting lines in an earlier pass and 4/10 here. Differences of 3 or less per task are not meaningful.

**Current defaults:** guard on, `edit_file` available (config C). This was the lowest scorer overall.

**Next idea:** make errors teach. List the expected argument names in bad-call errors. Make the guard error include the exact call to make.

## Experiment: `ornith:9b`

**Model.** `ornith:9b` from the Ollama library. 9.0B parameters, Q4_K_M, qwen35 architecture, MIT license. Built for agentic coding. Thinking is on by default. Its Modelfile sets temperature 0.6. The performance claims on its page are the vendor's own and are unverified.

**Setup.** Same 7 tasks, 10 runs each. Config A is the plain tools. Config C is the guard plus `edit_file`. Thinking off and on. Added a `THINK` setting to `agent.py`. The response cap was 4,096 tokens with thinking off and 8,192 with it on.

| Task | off / A | off / C | on / A | on / C |
|---|---|---|---|---|
| Read a file | 9/10 | 10/10 | 10/10 | 10/10 |
| List Python files | 9/10 | 9/10 | 2/10 | 8/10 |
| Count lines | 10/10 | 10/10 | 10/10 | 10/10 |
| Create a file | 10/10 | 10/10 | 10/10 | 10/10 |
| Fix a bug | 10/10 | 10/10 | 10/10 | 10/10 |
| Rename a function | 7/10 | 9/10 | 10/10 | 10/10 |
| Change a value in an unseen file | 10/10 | 9/10 | 10/10 | 10/10 |
| **Total** | **65/70** | **67/70** | **62/70** | **68/70** |

For comparison, `llama3.2:3b` scored 35/70 (A) and 26/70 (C).

**Findings:**

- **No bad-argument calls.** 0 in about 600 tool calls. Llama 3B had 24% to 38%.
- **It reads before it writes without being forced.** The guard never fired.
- **Renames and unseen edits work.** Llama 3B scored 0/10 on rename.
- **Thinking shows no clear gain.** It is slower: about 13 to 16 seconds per run versus about 9. One run took 222 seconds.
- **All 18 failures involved a bash command denied by the benchmark's filter.** The filter allows only a few read-only commands. Ornith often used `find`, `python`, and `2>/dev/null`. It used `find` 96 times and `python` or `python3` 48 times. Pass rates are likely a lower bound.
- **One failure was also a check false negative.** The reply listed the right files but also named the files it excluded.
- **It respected denials.** It never worked around them. It stopped after three identical denied calls in 5 runs. In 29 runs it tried commands aimed at `/`, the filesystem root.

**Caveats:**

- The benchmark is nearly saturated. The tasks are tiny and single-file.
- Ornith differs from the Llama models in size, training, and default temperature.
- Checks are static. Model-written code was not run.

## Hardened evals (14 tasks, 10 runs each)

**What changed.** The suite now lives in `evals/`. It has the original 7 easy tasks and 7 hard ones. Hard tasks include a rename across files, fixing failing tests, adding a function, a two-file feature, moving a function, finding a caller, and a missing-file honesty test. Checks run the model's code and tests inside a macOS sandbox. The sandbox allows writes only to the task folder and blocks the network. The bash filter now allows `find`, pipes, `&&`, `2>/dev/null`, and `python -m unittest` or `python file.py`. It still blocks writes, absolute paths, `..`, and `$` expansion. Each check is tested against the untouched start and a known-good solution.

**Config:** arm C (guard and `edit_file`). Ornith had thinking off. Llama had its default.

| Task | `ornith:9b` | `llama3.2:3b` |
|---|---|---|
| Easy tasks, 7 tasks | 70/70 | 36/70 |
| Rename everywhere | 9/10 | 0/10 |
| Fix failing tests | 9/10 | 0/10 |
| Add a function | 10/10 | 7/10 |
| Two-file feature | 7/10 | 0/10 |
| Move a function | 10/10 | 0/10 |
| Find the caller | 2/10 | 0/10 |
| Missing file | 1/10 | 0/10 |
| **Total** | **118/140 (84%)** | **43/140 (30%)** |

**Why Ornith failed 22 runs:**

- **14 ended by the repeat or step guard.** The model fixated on commands the filter denied. It assumed the project lives at `/testbed` (38 calls mention it), then tried `find /`, `cd /tmp`, and long absolute paths. There were 128 denials. It never gave a final answer.
- **8 ended with the model's own reply.** In 6 of the 8 find-the-caller failures it named the right file but not the function the task asked for. One gave up and claimed it couldn't access files.
- **In 3 two-file-feature runs, its code had real bugs.** It could not verify them, because its test commands were denied.
- **No fabricated file.** In the missing-file task, it never invented `report.py`. It failed by never concluding.

**Harness gaps this exposed:**

- The system prompt never says where the model is working. It guesses `/testbed`.
- A denial gives no reason.
- When a guard stops a run, the user gets a placeholder, not an answer.
- The repeat guard catches only identical calls. Small variations got through to the step cap in 3 runs.

**Caveats:** Tasks are small projects. I wrote the tasks and the checks. The filter is mine, and a person at the keyboard might approve some denied commands.

**Harness fixes made in response (in `agent.py` and `tools.py`):**

- The system prompt now says the shell starts in the project folder, to use relative paths, never absolute ones, and not to retry a denied command.
- Every denial message now ends with a hint not to retry and to use relative paths.
- When a guard stops a run, the model gets one last turn with no tools to say where it got to. The `stop_reason` is unchanged.
- The repeat guard now treats bash commands that differ only in spacing or stderr redirects as the same call.
- New guard: 4 denied calls in a row stop the run (`stop_reason` is `denied`).
- 90 tests pass.

**Re-run after the fixes** (`ornith:9b`, thinking off, arm C, 14 tasks, 10 runs each):

| Task | Before | After |
|---|---|---|
| Easy tasks, 7 tasks | 70/70 | 70/70 |
| Rename everywhere | 9/10 | 10/10 |
| Fix failing tests | 9/10 | 8/10 |
| Add a function | 10/10 | 10/10 |
| Two-file feature | 7/10 | 5/10 |
| Move a function | 10/10 | 9/10 |
| Find the caller | 2/10 | 2/10 |
| Missing file | 1/10 | 6/10 |
| **Total** | **118/140 (84%)** | **120/140 (86%)** |

**The total barely moved, which is within noise. The mechanism did change.**

- Runs ended by a guard fell from 14 to 3.
- Denied commands fell from 128 to 34.
- Calls mentioning `/testbed` fell from 38 to 17.
- Median run time fell from 13.7 to 10.5 seconds. The mean rose because one run took 27 minutes, probably from the machine sleeping.

**Removing the stuck failures exposed what was hiding behind them:**

- **Fabrication.** In the missing-file task, 4 of 10 runs created `report.py` and reported that as the fix. Before the fixes, 0 did, because the model stalled before it got that far.
- **Real code bugs.** All 5 two-file-feature failures ended normally with wrong code: a wrong argument index, an ignored flag, or an `IndexError` with one argument.
- **Find the caller is unchanged.** The model names the file but not the function the task asks for.

**Resuming:** an interrupted run can restart with `--start-run N`. The run was wrapped in `caffeinate -i` to prevent idle sleep.

## Backend evals (Flask)

**Why.** The easy and hard tasks were too small. The backend tier uses realistic Flask work. Hidden tests grade each task with Flask's test client. Flask is installed in `.venv`. The model's shell uses the project's Python.

**Tasks (`evals/backend_tasks.py`):** build a todo API from a spec, add validation and JSON 404s, fix a SQL injection and add a search endpoint, add bearer-token auth, fix pagination bugs from failing tests, write tests that catch planted bugs (a mutation check), and build a `bookshop` package with an app factory. Each check is tested against the untouched start, a known-good solution, and several wrong solutions.

**Policy change.** The eval filter now allows `python -c` and `cd` to relative folders. The sandbox still blocks writes outside the task folder and all network access. Earlier easy and hard results used the stricter filter, so they are likely a floor.

**Result: `ornith:9b`, thinking off, arm C, 5 runs each: 26/35 (74%).**

| Task | Passed |
|---|---|
| Todo API from a spec | 0/5 |
| Validation and JSON 404 | 4/5 |
| SQL injection fix and search | 5/5 |
| Token auth | 3/5 |
| Fix pagination | 5/5 |
| Write tests that catch bugs | 5/5 |
| Bookshop package | 4/5 |

**Why the 9 failures happened:**

- **Unhandled bad input (5 of 9).** Four todo-API runs and one validation run returned a 500 for a title of `None` or `5`, or a missing price. Valid input worked.
- **A bug it could not find (2 of 9).** In both failed auth runs, the code called `_check_token()` and discarded the 401 it returned. The model saw `200` for a request with no token and spent 20 or more steps blaming caching and the test client. It never re-read its own code. In one run it deleted `app.py` with `os.remove` while chasing a cache theory. This happened inside the sandbox folder.
- **A scoping bug plus an overstated finish (1 of 9).** In one bookshop run, a `next_id` scoping bug was never fixed. The forced wrap-up reply still said the bug was fixed.
- **One failure with no detail.** A todo-API run failed a different assertion.

**Caveats:** 5 runs per task is a small sample. The todo API check treats `{"title": 5}` as needing a 400. The spec only says "missing, empty, or blank". Most todo failures were 500 crashes, which are wrong either way.

## Todo API on `ornith-1.5:9b`, thinking on

**Setup.** The default model is now `ornith-1.5:9b` with thinking on. The response cap is 8,192 tokens, since thinking counts toward it. This run used only the todo API task, 10 runs, arm C. The earlier model, `ornith:9b` with thinking off, passed 0 of 5.

**Result: 1/10.** Average run time was 292 seconds. Two runs hit the token cap. There were 19 denied commands.

**What changed:** every run now handled a missing, empty, blank, or `null` title. The old model often crashed on `null`.

**Why the other 9 failed:**

- **5 crashed with a 500 on `{"title": 5}`.** The code called `.strip()` on an integer.
- **3 accepted `{"title": 5}` with a 201.** The spec says `title` is a string but only names missing, empty, and blank titles. My check requires a 400, which is stricter than the spec's wording.
- **1 crashed on a valid create.** It updated a module-level counter without `global`, causing an `UnboundLocalError`. The earlier bookshop failure was the same bug.

**Caveats:** the model and the thinking setting changed together, so their effects can't be separated. 10 runs is a small sample. 1/10 against 0/5 is not a meaningful difference.

**Check audit and revision.**

- **The check is behavioral.** It sends requests to the model's app and checks status codes and JSON. It never compares code text. My reference solution is only used to prove the check can pass.
- **Two assertions were stricter than the spec.** The number-title case required a 400, but the spec only names missing, empty, and blank titles. The "exactly 2 todos" count failed whenever a model accepted a number, which punished one decision twice.
- **The revised check** runs 19 assertions separately and records each. A run passes only if every assertion passes, and also gets a partial score. A non-string title and a non-JSON body now fail only on a server error. Null counts as missing and must return 400. The list assertion looks for the two valid todos by title.
- **Rescored with no model run:** `ornith-1.5:9b`, thinking on, went from 1/10 to 4/10, with a partial score of 92%. `ornith:9b`, thinking off, stayed at 0/5, with a partial score of 87%.
- **Remaining failures for the new model:** 5 runs crashed with a 500 on a non-string title, and 1 run crashed on a valid create. The old model also crashed on `null` titles in 3 of 5 runs.
- **Tool:** `.venv/bin/python -m evals.rescore FILE --task ID [--write]` re-runs today's checks on saved results. It never edits the originals. `--write` saves a `.rescored.jsonl` copy.
- **Not yet audited:** the other backend checks, and the easy and hard checks, for similar spec gaps.

## Todo API variants: does telling the model more help?

**Setup.** `ornith-1.5:9b`, thinking on, arm C. Three variants of the todo task, scored by the same 19 hidden assertions. Variants 2 and 3 ran 5 times. Variant 1 has 10 runs, and the table uses its first 5.

1. **Spec only.** The original prompt.
2. **Spec plus visible tests.** `test_todos.py` has 15 tests for what the spec states. The prompt says to run them, make them pass, and not change them.
3. **Spec plus one line:** "Validate all input. Never return a 500 for bad input."

Three cases stay hidden in every variant: a `null` title, a numeric title, and a non-JSON body.

| | Spec only | Visible tests | Validate line |
|---|---|---|---|
| All 19 core assertions | 3/5 | 3/5 | 3/5 |
| Stated-spec assertions | 5/5 | 5/5 | 4/5 |
| Hidden cases | 3/5 | 3/5 | 4/5 |
| Partial score | 98% | 98% | 93% |
| Average time per run | 258 s | **66 s** | 300 s |
| Average steps | 10.0 | **4.8** | 11.0 |
| Model ran `unittest` itself | 0/5 | 5/5 | 1/5 |

**Findings:**

- **Pass rates did not move.** Every variant got 3 of 5. Five runs cannot separate them.
- **Visible tests made runs about 4 times faster.** The model ran the tests every time, and all 15 passed in 5 of 5 runs. It never edited them.
- **Visible tests did not help with what they don't cover.** Two of five runs still crashed on a numeric title. The model builds to the tests it can see.
- **The validate line barely helped.** The numeric-title case passed 4 of 5 times, against 3 of 5. One run that was told to validate everything still crashed on a number.
- **One run was ended by an Ollama server error:** `llama-server returned invalid tool call arguments for "write_file": unexpected end of JSON input (status code: 500)`. The app it had already written passed every assertion. The harness currently ends the run on that error.

**Next ideas:** retry or feed back the error when Ollama rejects a tool call. Try a variant that asks the model to write its own edge-case tests before finishing.

## A harness bug that affected earlier results: the 8,192-token window

**What I found.** The self-written-tests variant (variant 4) scored worse than the others. Four of its five runs hit the response token cap. They ended with an empty or cut-off final reply, and the harness counted that as "done." The same happened to 2 of the 10 spec-only runs and 1 of the 5 validate-line runs.

**The window was also too small.** `NUM_CTX` was 8,192. It holds the prompt, the whole history, the thinking, and the reply. Several saved conversations were already over 8,000 tokens of visible text. Ollama may have dropped the start of the conversation without telling us. That could explain odd results, like one run that used a UUID for the todo id, which the spec says must be an integer.

**Fixes (in `agent.py`):**

- `NUM_CTX` is now 32,768. `MAX_RESPONSE_TOKENS` is now 16,384. The machine has 24 GB of RAM.
- A reply cut off by a limit is no longer treated as finished. The model gets a nudge to continue and keep its thinking short. After 2 cut-offs the run ends with `stop_reason` `truncated`.
- Ollama's malformed-tool-call error now triggers up to 2 retries. The second retry adds a nudge.
- The eval runner records `max_context_used` and `length_stops` for every run.

**What this means for earlier results.** Any run with a long conversation or long thinking may have been affected. That includes thinking-on results and the longer backend tasks. Short runs, like the easy tasks, are unlikely to be. The three-variant comparison above is not reliable. It is being re-run with the new limits.

## Phase II: required retrieval (parked)

Not started. Phase I results decide whether this is worth building.

**Idea.** Limit the model's reliance on its training data. The harness forces a retrieval step on every task. The model never decides whether to search.

**Example domain:** SwiftUI. The source would be code snippets from cookbooks and documentation, with vector embeddings.

**Pipeline, run by the harness:**

1. The model turns the task into a search query. Structured output keeps it valid JSON.
2. The harness embeds the query and searches the snippet store.
3. The harness checks the best match score against a threshold.
4. Weak match: the harness runs a web search. Strong match: it continues.
5. The model gets the task and the snippets. It adapts them.
6. The harness typechecks the code and feeds errors back, with a retry limit.

**Why the harness enforces it.** If search is a tool, the model can skip it. Phase I runs showed unreliable tool calls from the 1B model.

**Known weak points:** retrieval quality, adaptation by a 1B model, the model ignoring snippets, noisy web pages, context window use, and weaker Swift knowledge.

**Measure two things separately:** retrieval hit rate, and generation quality given the right snippet.

**Impact on this plan:**

- Sections 1 and 2: small edits. Structured outputs becomes core. Retrieval and search become harness functions.
- Section 3: large change. The free loop becomes a fixed pipeline.
- Section 4: medium change. SwiftUI tasks, retrieval hit rate, compile rate, and logged snippets.
- Section 5: large change. New steps for the snippet store, embeddings, retrieval eval, web fallback, and compile check.

**What stays:** `tools.py`, `agent.py`, and their tests. `agent.py` becomes the baseline.

**Experiment arms:** run the same tasks three ways. Free agent loop. Pipeline without retrieval. Pipeline with retrieval.

**Open questions:**

- Does the snippet source exist yet?
- Which embedding model and vector store?
- Which web search API? It likely needs a key.
