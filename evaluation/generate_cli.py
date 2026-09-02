"""Generation driver for a machine with a logged-in `claude` CLI.

Runs N samples per brief, with up to 3 repair rounds driven by checkpoint
errors, writing raw attempts into results/attempts/ in the layout that
check_attempts.py / aggregate.py consume.

In THIS repository's original evaluation the generations were produced by
Claude Haiku subagents instead (no CLI credentials were available in the
session); this script is the equivalent standalone path.

Usage:  python generate_cli.py [N] [model]
        python generate_cli.py 20 claude-haiku-4-5
Note: current Claude models do not accept a temperature parameter; variance
comes from default sampling.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from briefs import BRIEFS                              # noqa: E402
from checkpoints import check_attempt, errors_as_feedback   # noqa: E402

ATTEMPTS = HERE / "results" / "attempts"
MAX_ATTEMPTS = 4


def ask(prompt: str, model: str) -> str:
    out = subprocess.run(
        ["claude", "-p", prompt, "--model", model, "--output-format", "text"],
        capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:400])
    return out.stdout


def one_run(brief_name: str, run: int, model: str) -> None:
    prompt = (HERE / "prompts" / f"{brief_name}.md").read_text()
    text, feedback = None, None
    for attempt in range(MAX_ATTEMPTS):
        full = prompt if feedback is None else (
            prompt + "\n\nYour previous answer:\n" + text
            + "\n\n" + feedback + "\nReply with ONLY the corrected JSON.")
        text = ask(full, model)
        (ATTEMPTS / f"{brief_name}_r{run}_a{attempt}.json").write_text(text)
        rec = check_attempt(text)
        if rec["stage"] == "valid":
            return
        feedback = errors_as_feedback(rec)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    model = sys.argv[2] if len(sys.argv) > 2 else "claude-haiku-4-5"
    ATTEMPTS.mkdir(parents=True, exist_ok=True)
    for b in BRIEFS:
        for run in range(n):
            if (ATTEMPTS / f"{b['name']}_r{run}_a0.json").exists():
                continue
            print(f"{b['name']} r{run} ...", flush=True)
            one_run(b["name"], run, model)
    print("done - now run check_attempts.py then aggregate.py")
