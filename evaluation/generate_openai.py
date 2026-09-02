"""Generation driver for OpenAI-compatible APIs (OpenAI GPT models and Kimi).

Runs the same experiment as generate_api.py — N samples per brief, up to 3
stateless repair rounds driven by checkpoint errors verbatim — against any
OpenAI-compatible endpoint, so one script covers both event keys.

WHERE THE KEYS GO (environment variables only — never hardcode them):
    provider "openai":  OPENAI_API_KEY   (+ OPENAI_BASE_URL if the event
                                          gave you a proxy URL)
    provider "kimi":    KIMI_API_KEY or MOONSHOT_API_KEY
                        (+ KIMI_BASE_URL; default https://api.moonshot.ai/v1)

Usage:
    export OPENAI_API_KEY=...            # in your shell, not in any file
    python generate_openai.py openai gpt-5.6-luna 20 prompts_noexample
    python generate_openai.py kimi kimi-k2.6 20 prompts_noexample

    argv: provider  model  n_runs  prompt_dir(prompts|prompts_noexample)
    Attempts land in $EVAL_RESULTS (default "results"); pick a distinct dir
    per condition, e.g.
        EVAL_RESULTS=results_luna_noex python generate_openai.py ...
    then score with:
        EVAL_RESULTS=results_luna_noex python check_attempts.py
        EVAL_RESULTS=results_luna_noex python aggregate.py

The script is resumable (skips runs whose a0 file exists) and exits cleanly
on rate limits so you can rerun.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from openai import OpenAI, APIStatusError, APIConnectionError, RateLimitError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from briefs import BRIEFS                                    # noqa: E402
from checkpoints import check_attempt, errors_as_feedback    # noqa: E402

RESULTS = HERE / os.environ.get("EVAL_RESULTS", "results")
MAX_ATTEMPTS = 4                    # 1 first pass + up to 3 repairs

PROVIDERS = {
    "openai": {"key_env": ["OPENAI_API_KEY"],
               "base_env": "OPENAI_BASE_URL", "base_default": None},
    "kimi": {"key_env": ["KIMI_API_KEY", "MOONSHOT_API_KEY"],
             "base_env": "KIMI_BASE_URL",
             "base_default": "https://api.moonshot.ai/v1"},
}


def make_client(provider: str) -> OpenAI:
    cfg = PROVIDERS[provider]
    key = next((os.environ[e] for e in cfg["key_env"] if os.environ.get(e)), None)
    if not key:
        sys.exit(f"set {' or '.join(cfg['key_env'])} in your shell environment first")
    base = os.environ.get(cfg["base_env"]) or cfg["base_default"]
    return OpenAI(api_key=key, base_url=base)


def ask(client: OpenAI, prompt: str, model: str) -> str:
    # Minimal parameter set for cross-provider compatibility: some GPT-5
    # models reject temperature/max_tokens; defaults are fine for this task.
    response = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}])
    return response.choices[0].message.content or ""


def one_run(client: OpenAI, prompt_dir: str, brief_name: str,
            run: int, model: str) -> str:
    prompt = (HERE / prompt_dir / f"{brief_name}.md").read_text()
    text, feedback = "", None
    for attempt in range(MAX_ATTEMPTS):
        full = prompt if feedback is None else (
            prompt + "\n\nYour previous answer:\n" + text
            + "\n\n" + feedback + "\nReply with ONLY the corrected JSON.")
        text = ask(client, full, model)
        (RESULTS / "attempts" / f"{brief_name}_r{run}_a{attempt}.json").write_text(text)
        rec = check_attempt(text)
        if rec["stage"] == "valid":
            return f"valid after {attempt} repair(s)"
        feedback = errors_as_feedback(rec)
    return "failed after 3 repairs"


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in PROVIDERS:
        sys.exit(__doc__)
    provider, model = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    prompt_dir = sys.argv[4] if len(sys.argv) > 4 else "prompts_noexample"

    (RESULTS / "attempts").mkdir(parents=True, exist_ok=True)
    client = make_client(provider)

    for b in BRIEFS:
        for run in range(n):
            if (RESULTS / "attempts" / f"{b['name']}_r{run}_a0.json").exists():
                continue
            try:
                outcome = one_run(client, prompt_dir, b["name"], run, model)
            except RateLimitError as e:
                sys.exit(f"rate limit hit — rerun later to resume: {e}")
            except APIStatusError as e:
                sys.exit(f"API error {e.status_code}: {e}")
            except APIConnectionError as e:
                sys.exit(f"connection error — check network/base_url: {e}")
            print(f"{b['name']} r{run}: {outcome}", flush=True)

    print(f"done — now: EVAL_RESULTS={RESULTS.name} python check_attempts.py "
          f"&& EVAL_RESULTS={RESULTS.name} python aggregate.py")
