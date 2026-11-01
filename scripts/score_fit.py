#!/usr/bin/env python3
"""Score selected postings against the whole profile with the real ATS scorer.

    jobstore.py select --kw materials --limit 25 \
      | python3 -I score_fit.py --min 35 > ranked.jsonl

Reads the JSON lines `jobstore.py select` writes, attaches the scorer's
`jd_match.skill_coverage` to each as `fit` -- 0-100, the share of the
posting's stated requirements the profile covers -- and writes them back out
ordered by it.

**Not `jd_match.score`**, and that distinction is load-bearing. The scorer's
headline number is roughly `60 * skill_coverage + 40 * prose_coverage`, and
`prose_coverage` is vacuously 1.0 for a document with nothing in it: a profile
holding a name and an email address and no other content scores 40 against a
clinical research posting, where the real profile scores 18. A floor on that
number would admit an empty resume and reject a real one. Worse, the prose
half falls as a document grows -- more text means more requirements the
scorer can judge weakly answered -- so the blended score is not monotonic in
how much the person has done, which is the one property a floor needs.

`skill_coverage` is monotonic and was clean on every case tested: 0.556 for a
genuinely matching national-lab postdoc posting, 0.18-0.27 across the seven
irrelevant postings in the same corpus, 0.12 for a clinical-research posting,
and 0.0 for the empty profile and for a different person's profile entirely. It is still reported as `blended_score` for
reference, because that is the number /ijob-tailor shows.

Why this is a separate pass and not part of `select`: the TF-IDF `score`
`select` computes is a ranking, not a measurement. Its IDF is taken over
whatever candidate set the run happened to produce, so the same posting and
the same profile score differently depending on what else came back -- 0.0591,
0.0639 and 0.0723 across three runs, in testing. A number like that can order
a list but cannot answer "is this worth reading", because there is no value it
could be compared against. `tool`'s jd_match is absolute: same inputs, same
0-100, every time. So TF-IDF orders the corpus cheaply and this scores only
the top of it, which is the two-stage split the cost forces anyway. One
`tool` invocation takes about 1.5 s, so roughly 0.4 s a posting at the
default `--jobs 4`: ten seconds for a 25-row shortlist, and still some
minutes for a whole corpus, which is why only the top is measured.

What it is scored against is `inputs/profile-score.pdf`, the whole profile
rendered by profile_pdf.py -- every bullet, no selection. That makes the
number an upper bound on achievable fit: if everything the person has done
cannot match the posting, no tailored subset of it will either. It therefore
reads a few points higher than the number /ijob-tailor reports for a finished
one-page resume (45 vs 40, 18 vs 13 on two real postings), and the two should
not be shown side by side as if they were the same measurement.

Nothing is dropped and nothing is written back to the corpus. Every input line
comes out, `--min` only labels: a posting the floor rejects is still in the
output with `below_min` set, and one that could not be scored at all carries
`fit: null` and says why. A floor that silently ate postings would be the one
failure this whole pipeline exists to avoid.

Scores are not cached. The corpus deliberately holds no verdict column --
a stored judgement goes stale the moment the profile changes -- and at 1.5 s
a posting there is nothing worth the risk of serving a stale one.
"""

import argparse
import concurrent.futures as futures
import itertools
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)


def load_records(stream):
    """JSON lines, one record each -- what `select` writes to stdout.

    Tolerates a single JSON array too, since that is what anyone piping
    through `jq -s` ends up with.
    """
    raw = stream.read().strip()
    if not raw:
        return []
    if raw.lstrip().startswith("["):
        return json.loads(raw)
    out = []
    for n, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        # A bad line is skipped with a warning, never fatal. Aborting here
        # threw away every posting already scored because one upstream
        # script printed a warning onto stdout.
        try:
            rec = json.loads(line)
        except ValueError as exc:
            print("[score_fit] skipping line %d, not JSON: %s" % (n, exc),
                  file=sys.stderr)
            continue
        if not isinstance(rec, dict):
            print("[score_fit] skipping line %d, not a JSON object" % n,
                  file=sys.stderr)
            continue
        out.append(rec)
    return out


def posting_text(store, rec):
    """`select` strips the body to keep its output pipeable, so fetch it."""
    text = (rec.get("text") or "").strip()
    if text or store is None:
        return text
    row = store.db.execute("SELECT text FROM postings WHERE key=?",
                           (rec.get("key") or "",)).fetchone()
    return (row["text"] or "").strip() if row else ""


_SEQ = itertools.count()


def score_one(tool, profile_pdf, text, tmpdir, key):
    """One `tool` invocation. Returns (fit, detail, error)."""
    # A counter, not a hash of the key: two concatenated selects can carry
    # the same posting twice, and two threads writing one filename race.
    jd = os.path.join(tmpdir, "jd-%d.txt" % next(_SEQ))
    # errors="replace": a lone surrogate in a scraped body (\ud800 and
    # friends survive json.loads) raised UnicodeEncodeError here, and the
    # exception travelled up through fut.result() and killed the whole run.
    with open(jd, "w", encoding="utf-8", errors="replace") as fh:
        fh.write(text)
    try:
        proc = subprocess.run([tool, profile_pdf, "--jd", jd, "--json"],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, {}, str(exc)
    finally:
        try:
            os.remove(jd)
        except OSError:
            pass
    if proc.returncode != 0:
        return None, {}, (proc.stderr or "").strip()[-300:] or "scorer failed"
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None, {}, "scorer did not return JSON"
    match = data.get("jd_match") or {}
    matched = match.get("matched") or []
    missing = match.get("missing") or []
    if not matched and not missing:
        # The scorer found no requirements in this posting at all, so there
        # was nothing to cover and skill_coverage comes back a meaningless
        # 1.0. Seen on stub records -- a twelve-word body scored coverage 1.0
        # and blended score 0. Unmeasurable, which is not the same as bad.
        return None, {}, ("posting states no extractable requirements "
                          "(%d words) -- too thin to score"
                          % len(text.split()))
    cover = match.get("skill_coverage")
    if cover is None:
        return None, {}, "scorer returned no jd_match.skill_coverage"
    detail = {"blended": match.get("score"),
              "prose_coverage": match.get("prose_coverage"),
              "missing": missing}
    return int(round(cover * 100)), detail, ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--profile-pdf",
                    default=os.path.join(ENGINE, "inputs",
                                         "profile-score.pdf"),
                    help="whole-profile PDF from profile_pdf.py")
    ap.add_argument("--tool", default=os.path.join(ENGINE, "tool"),
                    help="the open-ATS scorer; defaults to the engine's own")
    ap.add_argument("--root", default=None,
                    help="corpus root, for fetching bodies `select` stripped")
    ap.add_argument("--min", type=float, default=None, metavar="N",
                    help="label anything under N `below_min`. Never drops it.")
    ap.add_argument("--jobs", type=int, default=4,
                    help="concurrent scorer processes (default 4)")
    ap.add_argument("--missing", action="store_true",
                    help="also emit the skills the scorer found missing")
    a = ap.parse_args(argv)

    if not os.path.exists(a.profile_pdf):
        print(json.dumps({
            "error": "no profile PDF at %s. Build it with "
                     "`python3 -I scripts/profile_pdf.py` (about a second), "
                     "or run /ijob-profile." % a.profile_pdf}),
            file=sys.stderr)
        return 2
    if not os.path.exists(a.tool):
        print(json.dumps({"error": "no scorer at %s -- run /ijob-setup"
                                   % a.tool}), file=sys.stderr)
        return 2

    # A compile failure leaves the previous PDF in place, so "it exists" is
    # not "it is current". Scoring against last week's profile is the one
    # failure mode worse than not scoring at all, so say so loudly.
    stale = ""
    prof_json = os.path.join(os.path.dirname(os.path.abspath(a.profile_pdf)),
                             "profile.json")
    try:
        if (os.path.exists(prof_json)
                and os.path.getmtime(prof_json)
                > os.path.getmtime(a.profile_pdf) + 1):
            stale = ("%s is older than %s -- rebuild it with "
                     "scripts/profile_pdf.py or these scores describe an "
                     "out-of-date profile" % (a.profile_pdf, prof_json))
            print(json.dumps({"warning": stale}), file=sys.stderr)
    except OSError:
        pass

    records = load_records(sys.stdin)
    if not records:
        print(json.dumps({"scored": 0, "note": "no records on stdin"}),
              file=sys.stderr)
        return 0

    store = None
    if any(not (r.get("text") or "").strip() for r in records):
        sys.path.insert(0, HERE)
        import jobstore  # noqa: E402  -- only needed to read bodies back
        store = jobstore.Store(a.root or jobstore.DEFAULT_ROOT)

    started = time.time()
    with tempfile.TemporaryDirectory(prefix="ijob-fit-") as tmpdir:
        texts = [posting_text(store, r) for r in records]
        with futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
            pending = {}
            for rec, text in zip(records, texts):
                if not text:
                    rec["fit"] = None
                    rec["fit_error"] = "no posting body held -- fetch it first"
                    continue
                pending[pool.submit(score_one, a.tool, a.profile_pdf, text,
                                    tmpdir, rec.get("key") or "")] = rec
            for fut in futures.as_completed(pending):
                rec = pending[fut]
                try:
                    fit, detail, err = fut.result()
                except Exception as exc:          # noqa: BLE001
                    # Whatever went wrong, it went wrong for one posting.
                    # Every record that came in has to go back out.
                    fit, detail, err = None, {}, "%s: %s" % (
                        type(exc).__name__, exc)
                rec["fit"] = fit
                if err:
                    rec["fit_error"] = err
                else:
                    rec["blended_score"] = detail.get("blended")
                    if a.missing:
                        rec["fit_missing"] = detail.get("missing")
    elapsed = time.time() - started

    below = 0
    for rec in records:
        if a.min is not None and rec.get("fit") is not None:
            rec["below_min"] = rec["fit"] < a.min
            below += bool(rec["below_min"])
    # Highest fit first; anything unscorable sorts last but is still emitted,
    # because a posting we failed to measure is not a posting we rejected.
    # No further tiebreak on purpose: Python's sort is stable, `fit` is an
    # integer percentage so ties are common, and the order underneath is the
    # TF-IDF ranking select computed. Breaking ties on a date would throw
    # that away, which is the one thing stage one was for.
    records.sort(key=lambda r: (r.get("fit") is None, -(r.get("fit") or 0)))
    for rec in records:
        # ensure_ascii=False keeps the output readable, but a lone surrogate
        # anywhere in the record makes the write to stdout itself raise --
        # which would lose every posting at the last possible moment. Fall
        # back to escaped ASCII for that one record.
        try:
            print(json.dumps(rec, ensure_ascii=False))
        except UnicodeEncodeError:
            print(json.dumps(rec, ensure_ascii=True))

    scored = sum(1 for r in records if r.get("fit") is not None)
    print(json.dumps({
        "scored": scored, "unscorable": len(records) - scored,
        "min": a.min, "below_min": below,
        "best": max((r["fit"] for r in records
                     if r.get("fit") is not None), default=None),
        "seconds": round(elapsed, 1),
        "scored_against": a.profile_pdf,
        "stale_profile_pdf": stale or None}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
