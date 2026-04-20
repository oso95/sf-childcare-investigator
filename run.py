#!/usr/bin/env python3
"""CLI entry. Run an investigation from the terminal."""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

# .env.local (gitignored, for secrets) wins over .env if both exist.
load_dotenv(".env.local", override=False)
load_dotenv(".env", override=False)

from sf_investigator.agent import run_investigation


def _build_prompt(args: argparse.Namespace) -> str:
    if args.query:
        return args.query
    parts = []
    if args.name:
        parts.append(f"Investigate the San Francisco facility named '{args.name}'.")
    if args.address:
        parts.append(f"Investigate the licensed SF child-care facility at '{args.address}'.")
    if args.capacity_min:
        parts.append(
            f"Sweep every SF facility with licensed capacity >= {args.capacity_min} "
            f"(cap investigation at {args.sweep_limit}) and flag physical-impossibility candidates."
        )
    if not parts:
        parts.append("Investigate 3 SF facilities with the highest capacity for physical impossibility.")
    parts.append("Produce a markdown report per facility.")
    return " ".join(parts)


def _print_event(event: dict) -> None:
    t = event["type"]
    if t == "assistant_text":
        text = event["text"].strip()
        if text:
            print(f"\n[assistant] {text}\n")
    elif t == "tool_call":
        print(f"[→ tool] {event['name']}({json.dumps(event['arguments'])})")
    elif t == "tool_result":
        summary = event["result"]
        if isinstance(summary, dict) and "count" in summary:
            print(f"[← tool] {event['name']} → count={summary['count']} ({event['elapsed_ms']}ms)")
        elif isinstance(summary, dict) and "error" in summary:
            print(f"[← tool] {event['name']} → ERROR {summary['error']}")
        else:
            print(f"[← tool] {event['name']} ({event['elapsed_ms']}ms)")


def main() -> int:
    p = argparse.ArgumentParser(description="SF childcare investigator")
    p.add_argument("query", nargs="?", help="Free-form investigation prompt")
    p.add_argument("--name", help="Facility name fragment")
    p.add_argument("--address", help="Street address, e.g. '1984 GREAT HIGHWAY'")
    p.add_argument("--capacity-min", type=int, help="Sweep all SF facilities with capacity >= N")
    p.add_argument("--sweep-limit", type=int, default=5, help="Max facilities to deep-investigate in sweep mode")
    p.add_argument("--max-turns", type=int, default=12)
    p.add_argument("--model", help="Override model (default from $MODEL)")
    p.add_argument("--json-out", help="Write full run JSON to this path")
    p.add_argument("--quiet", action="store_true", help="Skip live event log")
    args = p.parse_args()

    prompt = _build_prompt(args)
    print(f"[prompt] {prompt}\n")
    result = run_investigation(
        prompt,
        model=args.model,
        max_turns=args.max_turns,
        on_event=None if args.quiet else _print_event,
    )
    print("\n" + "=" * 80)
    print(result["report"])
    print("=" * 80)
    print(f"\n(turns={result['turns']}, tool_calls={len(result['tool_calls'])})")

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(
                {"report": result["report"], "turns": result["turns"], "tool_calls": result["tool_calls"]},
                f, indent=2, default=str,
            )
        print(f"[saved] {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
