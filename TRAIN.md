# Notes: Fine-tuning a small open model

Goal: make a small open model, like Llama 3.2, a focused expert. Example focus: Python backend development.

Status: research only. The harness build in `PLAN.md` is paused at step 2.

Parked for now: where to get training datasets.

## Can we fine-tune Llama 3.2?

**Yes.** The weights are open. A 1B model is small enough to train on cheap hardware.

A cloud GPU may not even be needed.

## Which technique

**Use LoRA or QLoRA.** They train a small set of add-on weights and leave the base model frozen.

**Why:** memory needs drop sharply, and the output is a small adapter file. A 1B model fits on a single consumer GPU.

**Full fine-tuning** updates every weight. It is possible at 1B, but costs more and is rarely needed.

## Tools

**Hugging Face stack.** `transformers`, `peft`, and `trl` are the standard libraries. Most tutorials use them.

**Unsloth.** It wraps those libraries and runs faster with less memory. It ships ready-made Colab notebooks for Llama 3.2.

**Axolotl and LLaMA-Factory.** You configure training in a YAML file instead of writing code.

**MLX (`mlx-lm`).** It fine-tunes with LoRA directly on Apple Silicon. This machine is a Mac, so a 1B run may work locally.

## Where to run it

**Free options:** Google Colab and Kaggle notebooks give a single GPU. That is enough for a 1B LoRA run.

**Paid options:** RunPod, Lambda, Vast.ai, and Modal rent GPUs by the hour. A small LoRA run typically costs a few dollars.

## Getting the result back into Ollama

1. Merge the LoRA adapter into the base model.
2. Convert the merged model to GGUF with `llama.cpp`.
3. Run `ollama create` with a Modelfile.

The harness then uses the new model by changing one constant.

## Risks for the goal

**Focus is achievable, but expect limits.** Fine-tuning shifts a model's style and habits. It adds little reasoning power to a 1B model.

**Forgetting is a real risk.** Train only on Python code, and the model can lose its tool-calling format. Training examples need to include tool calls.

**Harness logs could become data.** Successful runs could later feed training. That is one way around the dataset problem.

## Open questions

- Local on a Mac with MLX, or cloud with Colab and Unsloth?
- Where does the training data come from? (Parked.)
- How do we measure "focus"? The harness evals in `PLAN.md` could serve as the benchmark.

## Reducing hallucinations: rewarding "I don't know"

Source: "Why Language Models Hallucinate" (Kalai, Nachum, Vempala, Zhang, 2025). arXiv 2509.04664.

Read: the 16-page main text. The appendices were not read.

**This is a scoring argument, not a training recipe.** The main text has no training experiments.

### What the paper says

**Hallucinations start in pretraining.** Facts seen once in the data get guessed wrong later. If 20% of facts appear once, expect errors on at least 20% of them.

**They survive post-training because of grading.** Most benchmarks score right as 1, wrong as 0, and "I don't know" (IDK) as 0. Guessing always beats abstaining.

**The proposed fix is an explicit confidence target in the prompt.** The paper's wording:

> Answer only if you are > t confident, since mistakes are penalized t/(1-t) points, while correct answers receive 1 point, and an answer of "I don't know" receives 0 points.

**Example values:** t = 0.5 costs 1 point per error. t = 0.75 costs 2. t = 0.9 costs 9.

**Search alone doesn't fix it.** Binary grading still rewards guessing when search fails to give a confident answer. Search needs a trigger. IDK can be that trigger.

### How to apply it to llama3.2:1b

**Use the paper's scoring as the reward.** Correct is +1. IDK is 0. Wrong is -t/(1-t). Start with t = 0.5.

**Train with reinforcement learning.** GRPO in TRL or Unsloth fits. A cheaper route is fine-tuning on examples where the model's wrong answers are replaced with IDK.

**Make IDK a tool call, not text.** Teach the model to call `web_search(query)` instead of guessing. The harness in `PLAN.md` already has the tool loop for it.

**Add a small cost to searching.** Otherwise the model searches every time. For example, a correct answer after searching scores +0.8.

**Python backend work is easy to score.** Unit tests can grade answers automatically.

### Risks

**Always-IDK collapse.** Wrong answers now cost points, so a weak model may abstain constantly. Track the IDK rate.

**A 1B model may not know what it doesn't know.** The paper shows RL-trained models can become miscalibrated. Whether a 1B model can learn this is untested.

**Score with the same rules.** Plain accuracy punishes abstaining. Use the penalized score plus the IDK rate.

### Free first experiment

Put the paper's confidence-target text in the system prompt. Run the harness evals on `llama3.2:1b`. This costs no training.

If the model ignores it, that shows how much a training run would need to change.

## Would llama3.2:1b be honest about its confidence?

**Probably not.** This is an informed expectation. It has not been tested here.

**Asking for a confidence number is the weak spot.** Small models tend to state high confidence whether or not they are right.

**Instruction-tuned models are the worst case.** The paper's Figure 2 shows a pretrained model that is well calibrated. After reinforcement tuning, it becomes overconfident. `llama3.2:1b` is instruction-tuned.

**Calibration also improves with model size.** Earlier research found larger models know better what they know. A 1B model sits at the weak end.

### What works better

**Measure confidence from outside the model.** Don't ask it. Observe it. Accuracy matters more than speed here, so slower methods are affordable.

**Sample the same question many times.** If the answers agree, confidence is high. If they scatter, the model is guessing.

**Check the probabilities of its tokens.** Raw token probabilities often carry more signal than what the model says. Recent Ollama versions may expose them as logprobs. Verify this first.

**For code, run it.** Execute the output against unit tests. The model can't fake that signal.

### How to find out

**Run a calibration test.** Ask known-answer questions with the paper's confidence-target prompt. Record the stated confidence and whether the answer was right.

**Compare the two.** If it says 90% and is right 30% of the time, it is overconfident. The harness evals in `PLAN.md` can run this test.
