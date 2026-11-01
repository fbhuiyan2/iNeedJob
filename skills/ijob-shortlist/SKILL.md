---
name: ijob-shortlist
description: Narrow and rank job postings already collected, without fetching anything or spending quota. Use when the user asks what jobs they have, wants a list re-ranked or re-filtered, asks for a different slice of their collected postings, says "show me", "what do I have", "re-rank", "anything in Illinois", or invokes /ijob-shortlist.
---

# /ijob-shortlist — narrow what is already held, for nothing

This is `/ijob-scrape` with discovery switched off. It holds no rules of its
own: follow **`ijob-scrape/SKILL.md`**, with one change.

```bash
ENGINE="__ENGINE_PATH__"   # rewritten by install.sh
SCRAPE="$ENGINE/skills/ijob-scrape/SKILL.md"    # read this, then come back
```

If that still reads `__ENGINE_PATH__`, resolve it yourself, in this order: `$RESUME_TAILOR_HOME`, then **the directory this `SKILL.md` is being read from** (its repo root is two levels up, and that is always the right answer when you are reading the playbook out of a clone). Never guess a conventional path such as `$HOME/soft/resume-tailor-agent`: on the author's own machine that is the live repo, so a run meant for a test copy writes into the real corpus and the real profile. If neither resolves, stop and ask — do not proceed against a guessed root.

**Skip §4 (Discovery) entirely.** Run §1 (paths), §1a (the profile gate), §2
(read the request), §3 (preferences), then §5 (the funnel) onward. No source
command runs. No HTTP request is made. No quota is spent.

That includes §5b — the fit floor runs here too, and announce it here too.
Scoring is a local binary over text already on disk, so it costs seconds and
nothing else. "Re-rank with no floor" and "floor 15" are exactly the kind of
question this command exists to answer for free.

## Why this exists as its own command

Discovery costs metered quota — 200 requests a month per API, which do not come
back. Selection is arithmetic over text already on disk. Separating the verbs
means **"show me something different" can never spend money**: everything any
source ever returned is already in the corpus, bodies included, so a new
question is a new query over old data.

That guarantee is the whole point. Do not fetch to improve an answer here.

## When the corpus cannot answer

If the user asks for something the corpus does not hold — a location never
searched, an employer never enumerated, postings newer than the last discovery
run — say exactly that, and offer `/ijob-scrape`. Name what is missing and what
it would cost.

> Nothing in Oregon — the corpus has never been searched there. `/ijob-scrape`
> could look, at about 3 requests of your remaining 184 this month.

**Never quietly run a search to cover the gap.** An empty result from a corpus
that was never asked the question is a different fact from an empty result from
a market that has nothing, and the user is the one who decides whether closing
that gap is worth the quota.

## The one thing to say out loud

Report the funnel every time (§5): `9,412 held · 284 after filters · 61 after
keywords · showing 25`. It is how the user knows which filter to widen, and it
is the difference between "your filters are tight" and "the corpus is empty" —
which look identical in a result count and must never read the same.
