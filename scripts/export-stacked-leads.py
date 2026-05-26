#!/usr/bin/env python3
"""Export stacked tax × instrument leads for calling."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scraper-service"
sys.path.insert(0, str(ROOT))

from app.pipeline.list_stack import export_stacked_markdown, stack_lists


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--county", default="scott")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--min-lists", type=int, default=2)
    args = p.parse_args()

    stacked = stack_lists(args.county)
    hot = [s for s in stacked if s.list_count >= args.min_lists]
    path = export_stacked_markdown(args.county, limit=args.limit)
    print(f"Wrote {path} — {len(hot)} multi-list hits (min {args.min_lists} lists)")


if __name__ == "__main__":
    main()
