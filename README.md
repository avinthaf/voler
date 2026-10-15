# voler

A small coding agent that runs on your own computer.

It uses a local model through [Ollama](https://ollama.com). No cloud needed.

## Why this exists

I want to see how well a small model can code.

A good harness might help a lot. So I built the harness first, then measured it.

Training a model is on hold until I know what the harness can do.

## What it can do

The agent has four tools:

- `read_file` reads a file.
- `write_file` creates or replaces a file.
- `edit_file` changes one part of a file.
- `bash` runs a shell command.

You must approve every write and every command. It shows you a preview first.

## Safety rules

- The agent stays inside one project folder.
- It must read a file before it changes it.
- It stops if it repeats the same call three times.
- It stops if you deny four commands in a row.
- It stops after 25 steps.

## Setup

You need Python 3 and Ollama.

```
python3 -m venv .venv
.venv/bin/pip install ollama flask
ollama pull ornith-1.5:9b
```

## Run it

```
.venv/bin/python main.py --root path/to/your/project
```

Type a task and press enter.

Commands:

- `/reset` clears the conversation.
- `/exit` quits.

## Change the model

Open `agent.py` and edit `MODEL`. The default is `ornith-1.5:9b`.

Thinking is on by default. Change `THINK` to turn it off.

## Run the tests

```
.venv/bin/python -m unittest discover -s tests < /dev/null
```

## Evals

The `evals/` folder holds tasks that score the model. Some are easy. Some are hard.
Some ask it to build a small Flask API.

Hidden checks run against what the model builds. The model never sees them.

Run a task five times:

```
.venv/bin/python -m evals.run --model ornith-1.5:9b --think on --arm C --runs 5 --tasks b1_flask_todo_api
```

Read the scores:

```
.venv/bin/python -m evals.summarize evals/results/FILE.jsonl
```

Results are saved in `evals/results/`. Git ignores that folder.

## What I found so far

- Small Llama models often break tool calls. Ornith did not.
- Most early failures came from my harness, not the model.
- The model still misses bad input, like a title that is not text.
- Showing it the tests helped speed. It did not help accuracy.
- Asking it to write its own tests made things worse.
- Samples are small. Treat the numbers as hints.

## Other files

- `PLAN.md` has the plan, the design choices, and every result.
- `TRAIN.md` has notes on training. This is on hold.
