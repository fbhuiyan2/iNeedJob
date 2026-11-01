#!/usr/bin/env python3
"""Runs inside a throwaway uv environment; prints postings as JSON lines.

Not meant to be run directly. `search_jobspy.py` invokes it through

    uv run --with python-jobspy>=... python scripts/_jobspy_runner.py ...

so that JobSpy, pandas and their dependency tree live in uv's cache and never
in this repo, the system Python, or a virtualenv anyone has to remember to
activate. The rest of the repo stays standard-library-only; this one file is
the single place a third-party import is allowed, and it is quarantined behind
a subprocess boundary.

Indeed and LinkedIn only. JobSpy can also scrape Glassdoor, ZipRecruiter,
Google and others; those are deliberately not reachable from here. The two
that are reachable are each gated behind their own opt-in marker and their own
rate limits in search_jobspy.py, because their request economics differ by a
factor of fifty — Indeed returns 100 postings with descriptions in one
request, LinkedIn returns 10 without and then charges a request per
description.

Arguments arrive as one JSON object on argv[1] rather than as flags, so adding
a knob does not mean editing two argument parsers.
"""

import json
import sys

ALLOWED = ("indeed", "linkedin")


def main():
    args = json.loads(sys.argv[1])
    sites = [s for s in args.get("sites") or ["indeed"] if s in ALLOWED]
    if not sites:
        print(f"no allowed site in {args.get('sites')!r}; "
              f"this runner serves {ALLOWED}", file=sys.stderr)
        return 2
    try:
        from jobspy import scrape_jobs
    except ImportError as e:  # pragma: no cover - only without the uv wrapper
        print(f"jobspy import failed: {e}", file=sys.stderr)
        return 2

    df = scrape_jobs(
        site_name=sites,
        search_term=args["query"],
        location=args.get("location") or None,
        distance=args.get("distance") or 50,
        is_remote=bool(args.get("remote")),
        results_wanted=int(args.get("results", 50)),
        offset=int(args.get("offset") or 0),
        hours_old=args.get("hours_old") or None,
        country_indeed=args.get("country") or "usa",
        # Indeed puts the body in the search response and ignores this.
        # LinkedIn fetches each one separately, which is what makes it
        # expensive; search_jobspy.py charges the rate limiter accordingly.
        fetch_description=bool(args.get("fetch_description")),
        description_format="markdown",
        enforce_annual_salary=False,
        verbose=0,
    )
    if df is None or df.empty:
        return 0
    # to_json then back, because the frame holds numpy scalars, NaN and
    # datetime.date objects that json.dumps will not serialise.
    for row in json.loads(df.to_json(orient="records", date_format="iso")):
        print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
