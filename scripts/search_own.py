#!/usr/bin/env python3
"""Search the three OpenWeb Ninja job APIs and write results into the corpus.

Standard library only. One free key covers all three; each carries its own
200-requests/month free tier and must be subscribed separately in the portal.

    python3 -I search_own.py enumerate --employer "Sandia National Laboratories"
    python3 -I search_own.py discover  --role "computational materials scientist" \
                                       --location Illinois
    python3 -I search_own.py indeed    --query "computational scientist" \
                                       --location Illinois
    python3 -I search_own.py quota

Three subcommands because the APIs are good at different jobs (measured):

  enumerate -> JSearch. Matches a named employer precisely. Use when you know
               who you want: "what is open at X". The only arm that reaches
               the national labs.
  discover  -> Real-Time LinkedIn Data. Matches loosely, which is a defect for
               enumeration and the point for discovery: it surfaces employers
               not already on the watchlist. Also carries reliable posting
               timestamps, which JSearch often omits.
  indeed    -> Real-Time Indeed Data. A real `location` filter, which the other
               two only approximate, and the only metered arm that reports
               whether a posting has expired. Weak on national labs, which do
               not advertise on Indeed.

Quota is billed per PAGE, not per call: --pages 3 is one HTTP call and three
requests against the month. Neither API returns a remaining-quota header, so
the ledger in the corpus (jobstore.py) is the only guard against overspending.
Every run reserves budget before calling and records actual spend after.

Reads OWN_API_KEY from the environment, or from inputs/secrets.env.
Writes one JSON line per posting to stdout (without the body, so an agent can
read the result without pulling text into context) and the full records into
the corpus unless --no-store is given.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Piping into head/less closes stdout early; die quietly rather than dumping a
# BrokenPipeError traceback over the user's terminal.
try:
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (ImportError, AttributeError, ValueError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobstore  # noqa: E402

BASE = "https://api.openwebninja.com"
APIS = {
    "own_jsearch":  {"path": "/jsearch/search-v2", "limit": 200},
    "own_linkedin": {"path": "/realtime-linkedin-data/search", "limit": 200},
    "own_indeed":   {"path": "/realtime-indeed-data/search", "limit": 200},
}
TIMEOUT = 45
# Beside the repo, not beside the caller. The key belongs to the install, and
# /ijob-scrape is invoked from whatever directory the user is working in.
SECRETS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "inputs", "secrets.env")


def load_key():
    key = os.environ.get("OWN_API_KEY")
    if key:
        return key
    try:
        with open(SECRETS, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("OWN_API_KEY="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    raise SystemExit(
        "OWN_API_KEY not set. Put it in inputs/secrets.env or the environment.\n"
        "Get a free key at https://www.openwebninja.com/ (no credit card); see\n"
        "docs/scrape-source-setup.md.")


def call(api, params, key):
    url = BASE + APIS[api]["path"] + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-API-Key": key,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.load(resp)
            billed = resp.headers.get("x-rapidapi-billing", "")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.load(e).get("error", {}).get("message", "")
        except Exception:
            pass
        if e.code == 403 and "not subscribed" in detail.lower():
            raise SystemExit(
                f"{api}: not subscribed. Subscribe to this API on the free plan at\n"
                f"https://www.openwebninja.com/ — the key is shared but each API\n"
                f"carries its own free tier. (A 403 is not billed.)")
        if e.code == 429:
            raise SystemExit(f"{api}: rate limited (1000/hour). Back off and retry.")
        raise SystemExit(f"{api}: HTTP {e.code} {detail or e.reason}")
    except urllib.error.URLError as e:
        raise SystemExit(f"{api}: {e.reason}")
    # "Queries=1; Requests=3" — Requests is what the monthly quota counts.
    m = re.search(r"Requests\s*=\s*(\d+)", billed)
    return body, int(m.group(1)) if m else params.get("num_pages", 1)


def jobs_of(api, body):
    """JSearch nests under data.jobs; LinkedIn and Indeed return data as a list."""
    data = body.get("data")
    if isinstance(data, dict):
        return data.get("jobs") or []
    return data or []


def to_record(j):
    """Map an OpenWeb Ninja job onto fetch_posting.py's posting shape."""
    loc = j.get("job_location") or ", ".join(
        x for x in (j.get("job_city"), j.get("job_state"), j.get("job_country")) if x)
    return {
        "title": j.get("job_title") or "",
        "company": j.get("employer_name") or "",
        "location": loc or "",
        "url": j.get("job_apply_link") or "",
        "apply_url": j.get("job_apply_link") or "",
        "posted_on": j.get("job_posted_at_datetime_utc") or j.get("job_posted_at") or "",
        "employment_type": j.get("job_employment_type") or "",
        "compensation": j.get("job_salary") or j.get("job_salary_string") or "",
        "req_id": j.get("job_indeed_ref_num") or "",
        "department": "",
        "text": j.get("job_description") or "",
        "publisher": j.get("job_publisher") or "",
        "remote": bool(j.get("job_is_remote")),
        # Only the Indeed arm reports this. Everywhere else the metered tiers
        # cannot tell "gone" from "not matched by this query" (jobstore
        # sweep_end), so an explicit expiry flag is worth carrying through.
        "status": "closed" if j.get("job_indeed_expired") else "open",
    }


def search(api, query, pages, key, store, extra=None, dry_run=False):
    limit = APIS[api]["limit"]
    remaining = store.remaining(api, limit)
    if remaining is not None and remaining <= 0:
        raise SystemExit(f"{api}: monthly budget of {limit} requests is spent. "
                         f"Resets next month; use the corpus or another tier.")
    if remaining is not None and pages > remaining:
        print(f"[{api}] budget allows {remaining} more requests this month; "
              f"reducing {pages} pages to {remaining}", file=sys.stderr)
        pages = remaining
    params = {"query": query, "page": 1, "num_pages": pages}
    if api in ("own_jsearch", "own_indeed"):
        params["country"] = "us"
    params.update(extra or {})
    if dry_run:
        print(f"[{api}] would call {params}", file=sys.stderr)
        return []
    body, billed = call(api, params, key)
    used, lim, over = store.spend(api, billed, limit)
    if lim and used >= 0.8 * lim:
        print(f"[{api}] WARNING {used}/{lim} requests used this month", file=sys.stderr)
    return [to_record(j) for j in jobs_of(api, body)]


def main(argv=None):
    # The shared options are accepted on either side of the subcommand; argparse
    # does not do that by itself, and "quota --root X" is the obvious thing to
    # type. SUPPRESS keeps the subparser copy from clobbering the outer value
    # with its own default when the flag was given before the subcommand.
    def shared(parser, suppress):
        d = argparse.SUPPRESS if suppress else None
        parser.add_argument("--root", default=d or jobstore.DEFAULT_ROOT)
        parser.add_argument("--pages", type=int, default=d or 3,
                            help="pages of ~10 results; each costs one request "
                                 "(default 3)")
        parser.add_argument("--no-store", action="store_true", default=d or False,
                            help="print results without writing them to the corpus")
        parser.add_argument("--dry-run", action="store_true", default=d or False,
                            help="show what would be called and spend nothing")

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    shared(ap, False)
    common = argparse.ArgumentParser(add_help=False)
    shared(common, True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("enumerate", parents=[common],
                       help="JSearch: what is open at a named employer")
    p.add_argument("--employer", required=True, action="append")
    p.add_argument("--extra", default="", help="extra query terms")

    p = sub.add_parser("discover", parents=[common],
                       help="LinkedIn: who is hiring for a role")
    p.add_argument("--role", required=True, action="append")
    p.add_argument("--location", default="")

    p = sub.add_parser("indeed", parents=[common],
                       help="Indeed: free-text search with a real location filter")
    p.add_argument("--query", required=True, action="append",
                   help="employer or role; repeatable")
    p.add_argument("--location", default="", help="passed as a filter, not a term")

    sub.add_parser("quota", parents=[common], help="report budget for all three APIs")

    a = ap.parse_args(argv)
    store = jobstore.Store(a.root)

    if a.cmd == "quota":
        out = {}
        for api, cfg in APIS.items():
            out[api] = {"used_this_month": store.used(api),
                        "limit": cfg["limit"],
                        "remaining": store.remaining(api, cfg["limit"])}
        print(json.dumps(out, indent=1))
        store.close()
        return 0

    key = load_key()
    api = {"enumerate": "own_jsearch", "discover": "own_linkedin",
           "indeed": "own_indeed"}[a.cmd]
    # Indeed takes `location` as its own parameter; the other two have no such
    # filter and only honour a place name folded into the query string.
    extra = {"location": a.location} if a.cmd == "indeed" and a.location else None
    if a.cmd == "enumerate":
        queries = [f"{e} {a.extra}".strip() for e in a.employer]
    elif a.cmd == "discover":
        queries = [f"{r} {a.location}".strip() for r in a.role]
    else:
        queries = list(a.query)

    allrecs, failed = [], 0
    for i, q in enumerate(queries):
        if i:
            time.sleep(1.5)
        try:
            recs = search(api, q, a.pages, key, store, extra=extra,
                          dry_run=a.dry_run)
        except SystemExit as e:
            print(str(e), file=sys.stderr)
            failed += 1
            break
        for r in recs:
            r["query"] = q
        allrecs.extend(recs)
        print(f"[{api}] {q!r}: {len(recs)} results", file=sys.stderr)

    stored_keys = []
    if allrecs and not a.no_store and not a.dry_run:
        res = store.append(allrecs, api)
        stored_keys = res["keys"]
        split = (f", {res['split']} split off a key collision"
                 if res["split"] else "")
        print(f"[corpus] +{res['added']} new, {res['updated']} updated, "
              f"{res['unchanged']} already held{split}", file=sys.stderr)
    store.save()
    store.close()

    for i, r in enumerate(allrecs):
        slim = {k: v for k, v in r.items() if k != "text"}
        # The key the record actually landed under, not a recomputed one: a
        # posting that split on a weak-key collision lives at `id:...#2`, and
        # marking it by the recomputed key would silently miss.
        slim["key"] = (stored_keys[i] if i < len(stored_keys)
                       else jobstore.posting_key(r))
        slim["chars"] = len(r.get("text") or "")
        print(json.dumps(slim, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
