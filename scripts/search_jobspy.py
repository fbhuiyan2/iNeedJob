#!/usr/bin/env python3
"""Scrape Indeed and LinkedIn through JobSpy. Off by default; opt in per site.

    python3 -I search_jobspy.py check
    python3 -I search_jobspy.py enable --site indeed     # writes the opt-in marker
    python3 -I search_jobspy.py enable --site linkedin
    python3 -I search_jobspy.py search --site indeed \
                                       --query "computational scientist" \
                                       --location Illinois --hours-old 168
    python3 -I search_jobspy.py status
    python3 -I search_jobspy.py disable --site linkedin

READ THIS BEFORE ENABLING IT
----------------------------
These are the only sources in the repo that are **not** sanctioned by the
sites they read. Everything else is a public API, a first-party key, or a
vendor that absorbs the scraping on its own infrastructure. This one runs from
your machine, on your IP.

  * **Neither site's terms of service permit scraping.** Using this is your
    decision, not the tool's.
  * **A block lands on you.** Not on a vendor.
  * **It can break without warning.** JobSpy reads page structure. A redesign
    breaks it until the maintainers ship a fix — historically days, not
    months, but the failure mode in between is zero results rather than an
    error. `check --refresh` pulls the newest release.
  * **It needs Python and `uv`.** Nothing is installed into this repo or your
    system Python; `uv run --with` resolves JobSpy into its own cache.

**The two sites are not equivalent, and the difference is not a preference.**
Measured in JobSpy 1.4.1:

| | Indeed | LinkedIn |
|---|---|---|
| Postings per search request | 100 | 10 |
| Description | in the search response | **a second request per posting** |
| JobSpy's own delay | none | 3–7 s between search pages, none between descriptions |
| Requests for 50 postings with text | 1 | 55 |
| Endpoint | GraphQL API | the logged-out `jobs-guest` HTML endpoint |

So LinkedIn costs roughly **fifty times more traffic per posting**, and its
own code expects to be throttled — it has a branch for "unexpected page with
no jobs (blocked?)". That is why the two carry different limits, why
LinkedIn's per-call result count is capped, and why Indeed stays the default.

LinkedIn here is the **logged-out** endpoint: JobSpy clears cookies and sends
no credentials, so this is not your LinkedIn account being used, and a block
is an IP-level block rather than an account action. That is a smaller risk
than account scraping, not no risk.

Glassdoor, ZipRecruiter, Google and the rest of JobSpy's sites are not
reachable from here. The runner accepts `indeed` and `linkedin` and nothing
else.

Politeness is enforced in the corpus database, not in this process, so the
limits hold across separate invocations and across a crash: a minimum gap
between calls and a hard cap per hour (jobstore.Store.throttle), both charged
in HTTP requests rather than in calls. There is no reason to scrape fast —
every posting is written through to the corpus and never fetched twice
(the design notes).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

try:
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (ImportError, AttributeError, ValueError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobstore  # noqa: E402

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "_jobspy_runner.py")
# A floor, not a pin. The whole argument for this source is that breakage is
# fixed upstream within days, which only helps if we are allowed to pick the
# fix up. `check --refresh` forces uv to re-resolve.
SPEC = "python-jobspy>=1.4.1"
TIMEOUT = 900

# Per site, because the request economics differ by a factor of fifty (see the
# table above). `page_size` and `fetch_description` are JobSpy's behaviour,
# measured, not a policy choice; the limits are the policy.
#
# Indeed:   1 request -> 100 postings with text.   20s apart, 15/hour
#           = up to 1,500 postings an hour.
# LinkedIn: 1 request -> 10 postings, then one more request per description.
#           2s per request, 200/hour, and a hard 50 results per call because
#           JobSpy fires those description requests back to back with no sleep
#           of its own — a burst this process cannot slow from outside, so the
#           only control is to keep it short.
SITES = {
    "indeed": {
        "name": "Indeed",
        "source": "jobspy_indeed",
        "page_size": 100,
        "fetch_description": False,   # included in the search response
        "min_interval": 20.0,
        "max_per_hour": 15,
        "default_results": 100,
        "max_results": 0,             # 0 = no cap
        "marker": "jobspy-indeed-enabled",
        "legacy_marker": "jobspy-enabled",
    },
    "linkedin": {
        "name": "LinkedIn",
        "source": "jobspy_linkedin",
        "page_size": 10,
        "fetch_description": True,    # one extra request per posting
        "min_interval": 2.0,
        "max_per_hour": 200,
        "default_results": 25,
        "max_results": 50,
        "marker": "jobspy-linkedin-enabled",
        "legacy_marker": "",
    },
}


def opt_in_path(root, site):
    """Where consent for one site is recorded.

    In the corpus root, not in a cwd-relative path: consent is to scrape
    against *this* corpus, so it has to travel with the --root the caller
    passed. Enabling from the repo and then running from the user's own
    project directory must not report "not enabled" for the same corpus.
    """
    return os.path.join(root, SITES[site]["marker"])


def request_cost(site, results):
    """HTTP requests one search will make — the unit the site actually sees."""
    cfg = SITES[site]
    pages = max(1, -(-int(results) // cfg["page_size"]))
    return pages + (int(results) if cfg["fetch_description"] else 0)


CONSENT = """\
JobSpy scrapes {site} from THIS machine, on YOUR IP address.

  - {site}'s terms of service do not permit it.
  - If {site} blocks the traffic, it blocks you, not a vendor.
  - It reads {site}'s page layout, so a redesign silently returns zero
    results until JobSpy ships a fix.
  - This enables {site} only. Each site is a separate decision.
{extra}
Everything it finds is stored locally, so it never needs to run twice for the
same posting. Traffic is limited to one request per {interval:.0f}s and {cap}
requests per hour, held in the database across invocations — about {ceiling:,}
postings an hour.

NO WARRANTY, AND THE DECISION IS YOURS
  This software is provided "as is", without warranty of any kind, under the
  terms of the LICENSE file in this repository. Neither the repository nor its
  authors or contributors are responsible for how you use or modify it, for
  any breach of a third party's terms of service arising from your use of it,
  or for any consequence of that use. Enabling this source is your decision
  and the responsibility for it is yours alone.

Enabling is recorded in {marker}
Disable at any time with: search_jobspy.py disable --site {key}
"""

EXTRA = {
    "indeed": "",
    "linkedin": """\
  - This is the logged-out endpoint. JobSpy clears cookies and sends no
    credentials, so your LinkedIn account is not involved and a block is an
    IP-level block. Smaller risk than account scraping, not no risk.
  - LinkedIn costs ~50x more traffic per posting than Indeed: 10 postings per
    search request, plus one request per description. Calls are capped at
    {max_results} results each for that reason.
""",
}


def enabled(root, site):
    if os.path.exists(opt_in_path(root, site)):
        return True
    legacy = SITES[site]["legacy_marker"]
    return bool(legacy) and os.path.exists(os.path.join(root, legacy))


def require_uv():
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit(
            "uv is not installed, and this source needs it to run JobSpy "
            "without polluting the repo or your system Python.\n"
            "  curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            "Then re-run. Nothing else in this repo needs uv.")
    return uv


def run_jobspy(args, refresh=False):
    """Call the runner inside a uv environment and parse its JSON lines."""
    uv = require_uv()
    cmd = [uv, "run", "--quiet", "--with", SPEC]
    if refresh:
        cmd.append("--refresh")
    cmd += ["python", RUNNER, json.dumps(args)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise SystemExit("jobspy failed:\n  " + "\n  ".join(tail))
    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            out.append(json.loads(line))
    return out


def to_record(j, site):
    """Map a JobSpy row onto fetch_posting.py's posting shape."""
    amounts = [j.get("min_amount"), j.get("max_amount")]
    amounts = [f"{a:,.0f}" for a in amounts if a]
    comp = ""
    if amounts:
        comp = (j.get("currency") or "") + "-".join(amounts)
        if j.get("interval"):
            comp += f" / {j['interval']}"
    # job_url_direct is the employer's own ATS link when Indeed exposes it,
    # which is what lets posting_key() derive a real requisition id instead of
    # falling back to a hash of (employer, title, location).
    url = j.get("job_url_direct") or j.get("job_url") or ""
    return {
        "title": j.get("title") or "",
        "company": j.get("company") or "",
        "location": j.get("location") or "",
        "url": url,
        "apply_url": url,
        "posted_on": (j.get("date_posted") or "")[:10],
        "employment_type": j.get("job_type") or "",
        "compensation": comp,
        "department": j.get("job_function") or "",
        "req_id": j.get("id") or "",
        "text": j.get("description") or "",
        "publisher": site,
        "remote": bool(j.get("is_remote")),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=jobstore.DEFAULT_ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="is uv present and can JobSpy be resolved")\
       .add_argument("--refresh", action="store_true",
                     help="force uv to re-resolve, picking up a newer JobSpy")
    p = sub.add_parser("enable", help="record the opt-in after reading the warning")
    p.add_argument("--site", choices=sorted(SITES), default="indeed")
    p.add_argument("--yes", action="store_true", help="skip the prompt")
    p = sub.add_parser("disable", help="remove the opt-in marker")
    p.add_argument("--site", choices=sorted(SITES), default="indeed")
    sub.add_parser("status", help="opt-in state and recent request rate, per site")

    p = sub.add_parser("search", help="scrape one site for one or more queries")
    p.add_argument("--site", choices=sorted(SITES), default="indeed",
                   help="indeed (default) or linkedin; each is enabled "
                        "separately and carries its own limits")
    p.add_argument("--query", required=True, action="append")
    p.add_argument("--location", default="")
    p.add_argument("--distance", type=int, default=50, help="miles")
    p.add_argument("--remote", action="store_true",
                   help="Indeed only; LinkedIn's endpoint ignores it")
    p.add_argument("--results", type=int, default=0,
                   help="per query. Default 100 for Indeed (one request), "
                        "25 for LinkedIn (capped at 50, because each posting "
                        "costs an extra request)")
    p.add_argument("--hours-old", type=int,
                   help="only postings newer than this; use it, it is cheap "
                        "on both sites and keeps repeat sweeps small")
    p.add_argument("--country", default="usa", help="Indeed only")
    p.add_argument("--min-interval", type=float,
                   help="seconds per request (default: the site's)")
    p.add_argument("--max-per-hour", type=int,
                   help="requests per hour (default: the site's)")
    p.add_argument("--no-store", action="store_true")
    p.add_argument("--dry-run", action="store_true")

    a = ap.parse_args(argv)

    if a.cmd == "check":
        require_uv()
        rows = run_jobspy({"sites": ["indeed"], "query": "test",
                           "location": "", "results": 1}, refresh=a.refresh)
        print(json.dumps({"uv": shutil.which("uv"), "spec": SPEC,
                          "jobspy_runs": True, "sample_rows": len(rows),
                          "enabled": {k: enabled(a.root, k) for k in SITES}}))
        return 0

    if a.cmd == "enable":
        cfg = SITES[a.site]
        marker = opt_in_path(a.root, a.site)
        os.makedirs(os.path.dirname(marker) or ".", exist_ok=True)
        # Postings per hour, not requests per hour: for LinkedIn the two
        # differ by the per-description request, and quoting the request
        # number alone would make the limit sound far more generous than it is.
        per_posting = request_cost(a.site, 100) / 100.0
        text = CONSENT.format(
            site=cfg["name"], key=a.site,
            extra=EXTRA[a.site].format(max_results=cfg["max_results"]),
            interval=cfg["min_interval"], cap=cfg["max_per_hour"],
            ceiling=int(cfg["max_per_hour"] / per_posting), marker=marker)
        print(text, file=sys.stderr)
        if not a.yes:
            try:
                if input(f"Enable {a.site} scraping? [y/N] ").strip().lower() \
                        not in ("y", "yes"):
                    print("not enabled", file=sys.stderr)
                    return 1
            except EOFError:
                print("no tty; re-run with --yes if you accept the above",
                      file=sys.stderr)
                return 1
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(json.dumps({"enabled": True, "marker": marker}))
        return 0

    if a.cmd == "disable":
        existed = False
        for name in (SITES[a.site]["marker"], SITES[a.site]["legacy_marker"]):
            if name and os.path.exists(os.path.join(a.root, name)):
                os.remove(os.path.join(a.root, name))
                existed = True
        print(json.dumps({"site": a.site, "enabled": False, "removed": existed}))
        return 0

    store = jobstore.Store(a.root)
    if a.cmd == "status":
        out = {"uv": shutil.which("uv"), "spec": SPEC, "sites": {}}
        for key, cfg in sorted(SITES.items()):
            per_posting = request_cost(key, 100) / 100.0
            out["sites"][key] = {
                "enabled": enabled(a.root, key),
                "marker": opt_in_path(a.root, key),
                "source": cfg["source"],
                "postings_per_search_request": cfg["page_size"],
                "extra_request_per_description": cfg["fetch_description"],
                "requests_per_100_postings": request_cost(key, 100),
                "min_interval_s": cfg["min_interval"],
                "max_requests_per_hour": cfg["max_per_hour"],
                "postings_per_hour_ceiling": int(cfg["max_per_hour"] / per_posting),
                "max_results_per_call": cfg["max_results"] or None,
                **store.rate_status(cfg["source"])}
        print(json.dumps(out, indent=1))
        store.close()
        return 0

    # -- search
    cfg = SITES[a.site]
    source = cfg["source"]
    if not enabled(a.root, a.site):
        store.close()
        raise SystemExit(
            f"{source} is not enabled. It scrapes {cfg['name']} from your own "
            f"IP, against {cfg['name']}'s terms of service.\n"
            f"Read the warning and opt in with:  "
            f"search_jobspy.py enable --site {a.site}")

    results = a.results or cfg["default_results"]
    if cfg["max_results"] and results > cfg["max_results"]:
        store.close()
        raise SystemExit(
            f"--results {results} is above the {cfg['max_results']} cap for "
            f"{a.site}. Each posting costs an extra request there and JobSpy "
            f"fires them back to back, so a long call is one long burst. Run "
            f"several shorter calls — the throttle will space them.")
    # Always fetch the body where it is a separate request. A record with no
    # text cannot be ranked against the profile, cannot be tailored against,
    # and yields no work-authorisation flags — so the cheap sweep that skips
    # it buys a list of titles that still has to be re-fetched one by one.
    descriptions = cfg["fetch_description"]
    if a.remote and a.site == "linkedin":
        print("[warn] --remote is ignored by LinkedIn's endpoint; filter with "
              "`jobstore.py select --work-mode remote` afterwards",
              file=sys.stderr)

    min_interval = cfg["min_interval"] if a.min_interval is None else a.min_interval
    max_per_hour = cfg["max_per_hour"] if a.max_per_hour is None else a.max_per_hour

    allrecs, failed = [], 0
    for q in a.query:
        args = {"sites": [a.site], "query": q, "location": a.location,
                "distance": a.distance, "remote": a.remote, "results": results,
                "hours_old": a.hours_old, "country": a.country,
                "fetch_description": descriptions}
        # What the site will actually see. Pages, plus one request per
        # description when the body is a separate fetch (LinkedIn).
        cost = request_cost(a.site, results)
        if a.dry_run:
            print(f"[{source}] would scrape {args} ({cost} requests)",
                  file=sys.stderr)
            continue
        try:
            waited = store.throttle(source, min_interval, max_per_hour,
                                    cost=cost)
        except SystemExit as e:
            print(str(e), file=sys.stderr)
            failed += 1
            break
        if waited:
            print(f"[{source}] waited {waited:.0f}s for the rate limit "
                  f"({cost} request{'s' if cost > 1 else ''})", file=sys.stderr)
        try:
            rows = run_jobspy(args)
        except SystemExit as e:
            print(str(e), file=sys.stderr)
            failed += 1
            continue
        recs = [to_record(r, a.site) for r in rows]
        for r in recs:
            r["query"] = q
        allrecs.extend(recs)
        bodies = sum(1 for r in recs if r["text"])
        print(f"[{source}] {q!r}: {len(recs)} results, {bodies} with text",
              file=sys.stderr)
        if not recs:
            print(f"[{source}] zero results. That is sometimes real and "
                  f"sometimes {cfg['name']} changing their markup — try "
                  f"`check --refresh` to pick up a newer JobSpy.",
                  file=sys.stderr)

    stored_keys = []
    if allrecs and not a.no_store and not a.dry_run:
        res = store.append(allrecs, source)
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
