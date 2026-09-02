"""Generation driver over the Claude API (Anthropic SDK).

Runs the full resilience / self-correction experiment: N samples per brief,
each with up to 3 stateless repair rounds driven by the checkpoint errors
verbatim, writing attempts in the layout check_attempts.py / aggregate.py
consume. Unlike the subagent-driven run, this needs only an API key and is
not bound to a desktop-app subscription limit.

Auth: export ANTHROPIC_API_KEY in your shell before running — do not paste
the key anywhere else; the SDK reads it from the environment.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python generate_api.py [N] [model] [prompt_dir]
    python generate_api.py 20 claude-haiku-4-5 prompts             # main condition
    EVAL_RESULTS=results_ablation python generate_api.py 20 claude-haiku-4-5 prompts_noexample

Model defaults to claude-haiku-4-5 — the generator the shipped results
measured; pass claude-sonnet-5 or claude-opus-5 to test a stronger one.
Note: Claude 5-family models reject a temperature parameter; variance comes
from default sampling (Haiku 4.5 still accepts --temperature).

Then:  EVAL_RESULTS=... python check_attempts.py && python aggregate.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anthropic

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from briefs import BRIEFS                                    # noqa: E402
from checkpoints import check_attempt, errors_as_feedback    # noqa: E402

RESULTS = HERE / os.environ.get("EVAL_RESULTS", "results")
MAX_ATTEMPTS = 4                    # 1 first pass + up to 3 repairs


def ask(client: anthropic.Anthropic, prompt: str, model: str,
        temperature: float | None) -> str:
    kwargs = {}
    if temperature is not None and "haiku" in model:
        kwargs["temperature"] = temperature      # rejected by Claude 5 family
    response = client.messages.create(
        model=model, max_tokens=8000,
        messages=[{"role": "user", "content": prompt}], **kwargs)
    return "".join(b.text for b in response.content if b.type == "text")


def one_run(client: anthropic.Anthropic, prompt_dir: str,
            brief_name: str, run: int, model: str, temperature: float | None) -> str:
    prompt = (HERE / prompt_dir / f"{brief_name}.md").read_text()
    text, feedback = "", None
    for attempt in range(MAX_ATTEMPTS):
        full = prompt if feedback is None else (
            prompt + "\n\nYour previous answer:\n" + text
            + "\n\n" + feedback + "\nReply with ONLY the corrected JSON.")
        text = ask(client, full, model, temperature)
        (RESULTS / "attempts" / f"{brief_name}_r{run}_a{attempt}.json").write_text(text)
        rec = check_attempt(text)
        if rec["stage"] == "valid":
            return f"valid after {attempt} repair(s)"
        feedback = errors_as_feedback(rec)
    return "failed after 3 repairs"


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    model = sys.argv[2] if len(sys.argv) > 2 else "claude-haiku-4-5"
    prompt_dir = sys.argv[3] if len(sys.argv) > 3 else "prompts"
    temperature = 1.0

    (RESULTS / "attempts").mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic()      # reads ANTHROPIC_API_KEY from the env

    for b in BRIEFS:
        for run in range(n):
            if (RESULTS / "attempts" / f"{b['name']}_r{run}_a0.json").exists():
                continue                 # resumable
            try:
                outcome = one_run(client, prompt_dir, b["name"], run, model, temperature)
            except anthropic.RateLimitError as e:
                sys.exit(f"rate/spend limit hit — rerun later to resume: {e}")
            except anthropic.APIStatusError as e:
                sys.exit(f"API error {e.status_code}: {e.message}")
            except anthropic.APIConnectionError as e:
                sys.exit(f"connection error — check network and retry: {e}")
            print(f"{b['name']} r{run}: {outcome}", flush=True)

    print("done — now: "
          f"EVAL_RESULTS={RESULTS.name} python check_attempts.py && "
          f"EVAL_RESULTS={RESULTS.name} python aggregate.py")
