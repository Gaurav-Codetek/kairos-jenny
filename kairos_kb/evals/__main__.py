"""python -m kairos_kb.evals [--suite classification,diagnosis,e2e | all] [--repeat N] [--case ID ...]"""

import argparse
import asyncio
import logging
import sys

from kairos_kb.evals.runner import DEFAULT_SUITES, SUITES, format_report, run_evals


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m kairos_kb.evals", description=__doc__)
    parser.add_argument("--suite", default=",".join(DEFAULT_SUITES),
                        help=f"comma-separated from {SUITES}, or 'all' (e2e takes minutes per incident)")
    parser.add_argument("--repeat", type=int, default=3, help="classification calls per incident")
    parser.add_argument("--case", nargs="*", help="only these golden case ids")
    args = parser.parse_args()

    suites = SUITES if args.suite == "all" else tuple(s.strip() for s in args.suite.split(",") if s.strip())
    unknown = set(suites) - set(SUITES)
    if unknown:
        parser.error(f"unknown suite(s): {sorted(unknown)}")

    logging.disable(logging.WARNING)  # the report is the output; keep SQL/HTTP logs out of it
    report = asyncio.run(run_evals(suites, args.repeat, args.case))
    print(format_report(report))
    failed = [r for r in report["results"] if not r.get("skipped") and not r.get("passed")]
    return 1 if failed or report["regressions"] else 0


if __name__ == "__main__":
    sys.exit(main())
