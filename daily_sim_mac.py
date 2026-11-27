"""
Daily Simulation CLI (macOS flavor) — simulate ~20 working days of daily activity
on an existing macOS Cold Start world.

Usage:
    uv run python daily_sim_mac.py --world-id gdpeval_world_000000
    uv run python daily_sim_mac.py --world-id gdpeval_world_000000 --weeks 2
    uv run python daily_sim_mac.py --world-id gdpeval_world_000000 --start-date 2026-02-02
    uv run python daily_sim_mac.py --world-id gdpeval_world_000000 --model claude-sonnet-4-6
"""

import argparse
import os
import sys
from datetime import datetime

import anyio

from agents.daily_execution_mac import daily_simulate_mac


def main():
    parser = argparse.ArgumentParser(
        description="Daily Simulation (macOS): simulate daily work on an existing Cold Start world"
    )

    parser.add_argument(
        "--world-id",
        type=str,
        required=True,
        help="World ID (directory name under worlds/)",
    )
    parser.add_argument(
        "--worlds-root",
        type=str,
        default="worlds",
        help="Root directory for worlds. Default: worlds/",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Simulation start date (YYYY-MM-DD). Default: today",
    )
    parser.add_argument(
        "--weeks",
        type=int,
        default=4,
        help="Number of weeks to simulate. Default: 4",
    )
    parser.add_argument(
        "--plugins",
        type=str,
        nargs="*",
        default=None,
        help="Paths to plugin/skill directories to load into Claude Code",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Claude model to use (e.g. claude-sonnet-4-6). Default: SDK default.",
    )
    parser.add_argument(
        "--eval-model",
        type=str,
        default=None,
        help="Override model for Step 9 evaluation only. Default: same as --model.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Only run Steps 6 and 6.5 (monthly objectives + external NPC ref files), then stop.",
    )
    parser.add_argument(
        "--use-occupation-skills",
        action="store_true",
        help="Inject an 'Occupation Skills' hint into Steps 7/8 prompts, "
             "nudging the agent to read the matching skill under "
             ".claude/skills/ (e.g. 'lawyers', 'registered-nurses') before "
             "planning / producing deliverables. Skills must have been copied "
             "into each world's .claude/skills/ beforehand.",
    )

    args = parser.parse_args()

    world_dir = os.path.join(args.worlds_root, args.world_id)
    if not os.path.isdir(world_dir):
        print(f"Error: world directory not found: {world_dir}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(os.path.join(world_dir, "_complete")):
        print(
            f"Error: world {args.world_id} has not completed Cold Start. "
            f"Run cold_start_mac.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    plugins = None
    if args.plugins:
        plugins = [{"type": "local", "path": os.path.normpath(p)} for p in args.plugins]

    start_date = args.start_date or datetime.now().strftime("%Y-%m-%d")

    async def run():
        try:
            result_dir = await daily_simulate_mac(
                world_dir=world_dir,
                start_date=start_date,
                num_weeks=args.weeks,
                plugins=plugins,
                model=args.model,
                eval_model=args.eval_model,
                plan_only=args.plan_only,
                use_occupation_skills=args.use_occupation_skills,
            )
            if args.plan_only:
                print(f"\nSteps 6 & 6.5 complete: {result_dir}")
            else:
                print(f"\nDaily Simulation (macOS) complete: {result_dir}")
        except Exception:
            import traceback
            traceback.print_exc()
            sys.exit(1)

    anyio.run(run)


if __name__ == "__main__":
    main()
