#!/usr/bin/env python3
"""Persistent posting corpus, seen-set and quota ledger for /ijob-scrape.

Standard library only (sqlite3 ships with Python). No pip install, no API key.

    python3 -I jobstore.py add        --source own_jsearch < records.jsonl
    python3 -I jobstore.py ingest     --dir path/to/fetched-posting/
    python3 -I jobstore.py known      --key KEY [--key KEY ...]
    python3 -I jobstore.py get        --key KEY [--text]
    python3 -I jobstore.py find       [--employer X] [--status open] [--since DAYS]
    python3 -I jobstore.py mark       --key KEY --disposition dismissed
    python3 -I jobstore.py sweep-end  --source direct [--employer X]
    python3 -I jobstore.py budget     --api own_jsearch [--spend N] [--limit N]
    python3 -I jobstore.py watchlist  [--add EMPLOYER --board URL --platform P]
    python3 -I jobstore.py select     --kw materials --role postdoc,faculty \
                                      --work-mode remote,hybrid --state IL,CA \
                                      --auth-exclude citizen,clearance
    python3 -I jobstore.py tag        --key KEY --add shortlist
    python3 -I jobstore.py brief      --key KEY [--out DIR]
    python3 -I jobstore.py reclassify
    python3 -I jobstore.py purge      --older-than 365 --yes
    python3 -I jobstore.py stats
    python3 -I jobstore.py dump       [--text]

Why this exists: the metered discovery tiers are billed per page of results,
which works out to roughly two queries a day. Re-buying text we already hold
would make them unaffordable, so every record any tier returns is written
through to disk and never fetched twice.

SQLite rather than a JSON file because the corpus is append-heavy and read on
every run: a full posting body is several kilobytes, so a flat file would be
parsed in its entirety just to answer "do we already have this key?". Here that
is an indexed lookup, and an update is an UPSERT instead of a rewrite. The
`history` table keeps the append-only record a flat log would have given, and
`dump` writes JSON lines back out for eyeballing.

Default root is inputs/scrape/ (gitignored); the database is jobs.db.
"""

import argparse
import datetime as _dt
import difflib
import hashlib
import json
import os
import re
import sqlite3
import sys
import unicodedata

# Piping into head/less closes stdout early; die quietly rather than dumping a
# BrokenPipeError traceback over the user's terminal.
try:
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (ImportError, AttributeError, ValueError):
    pass

# Anchored to the repo, not the current directory. A bare `jobstore.py stats`
# run from somewhere else used to create a second, empty corpus beside
# whatever directory the agent happened to be in, and report it as the truth.
ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROOT = os.path.join(ENGINE_ROOT, "inputs", "scrape")
DB_NAME = "jobs.db"

# An aggregator record is a pointer; a direct-board record is the posting
# itself. Higher wins when two tiers describe the same job.
TIER = {"manual": 110, "direct": 100, "usajobs": 90,
        "own_jsearch": 40, "own_linkedin": 40, "own_indeed": 40,
        # Scraped Indeed. Good records — often the employer's own ATS link —
        # but unsanctioned, so a vendor record of the same job is preferred.
        "jobspy_indeed": 35,
        # Scraped LinkedIn. Same unsanctioned footing as jobspy_indeed and a
        # thinner record — the body is a second fetch per posting and is not
        # always there — so it loses to every vendor tier and to Indeed.
        "jobspy_linkedin": 22,
        "linkedin_guest": 20, "muse": 20, "serpapi": 20}

DISPOSITIONS = ("new", "shown", "dismissed", "tailored", "applied")

# Columns mirroring fetch_posting.py's posting dict, so tier 1 and the
# aggregators write one shape.
POSTING_FIELDS = ("title", "company", "location", "url", "apply_url",
                  "posted_on", "employment_type", "compensation", "department",
                  "req_id", "text", "publisher")

SCHEMA = """
CREATE TABLE IF NOT EXISTS postings (
    key          TEXT PRIMARY KEY,
    title        TEXT NOT NULL DEFAULT '',
    company      TEXT NOT NULL DEFAULT '',
    company_norm TEXT NOT NULL DEFAULT '',
    location     TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL DEFAULT '',
    apply_url    TEXT NOT NULL DEFAULT '',
    posted_on    TEXT NOT NULL DEFAULT '',
    employment_type TEXT NOT NULL DEFAULT '',
    compensation TEXT NOT NULL DEFAULT '',
    department   TEXT NOT NULL DEFAULT '',
    req_id       TEXT NOT NULL DEFAULT '',
    text         TEXT NOT NULL DEFAULT '',
    publisher    TEXT NOT NULL DEFAULT '',
    remote       INTEGER NOT NULL DEFAULT 0,
    source       TEXT NOT NULL DEFAULT '',
    tier         INTEGER NOT NULL DEFAULT 0,
    seen_via     TEXT NOT NULL DEFAULT '[]',
    query        TEXT NOT NULL DEFAULT '',
    first_seen   TEXT NOT NULL DEFAULT '',
    last_seen    TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'open',
    status_at    TEXT NOT NULL DEFAULT '',
    text_origin  TEXT NOT NULL DEFAULT '',
    -- Identity is the key's weaker twin: normalised (employer, title,
    -- location). Two rows sharing it are the same job even when the URL id
    -- differs, which is what a repost looks like.
    identity     TEXT NOT NULL DEFAULT '',
    repost_of    TEXT NOT NULL DEFAULT '',
    repost_count INTEGER NOT NULL DEFAULT 0,
    first_posted TEXT NOT NULL DEFAULT '',
    -- Derived from the title and the employer so the coarse cuts a human
    -- would make first ("postdocs at national labs") are a WHERE clause
    -- rather than a pass over every body. Recomputed by `reclassify`.
    role_class   TEXT NOT NULL DEFAULT '',
    sector       TEXT NOT NULL DEFAULT '',
    -- Also derived, also recomputed by `reclassify`. These are the cuts the
    -- `remote` flag and the free-text `location` could not make: three-way
    -- work mode rather than a boolean, a state code rather than a string to
    -- LIKE against, and the work-authorisation gates (§2c) read out of the
    -- body once at insert instead of scanned for on every run.
    work_mode    TEXT NOT NULL DEFAULT '',   -- remote | hybrid | onsite | ''
    state        TEXT NOT NULL DEFAULT '',   -- USPS code, '' when not US/unknown
    country      TEXT NOT NULL DEFAULT '',   -- ISO-ish 2 letters, '' when unknown
    auth         TEXT NOT NULL DEFAULT '',   -- comma-joined AUTH_PATTERNS names
    -- Not derived and never touched by `reclassify`: free-form labels the
    -- user or the agent attaches by hand, including to correct a derived
    -- column that got it wrong.
    tags         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_company   ON postings(company_norm);
CREATE INDEX IF NOT EXISTS ix_status    ON postings(status);
CREATE INDEX IF NOT EXISTS ix_last_seen ON postings(last_seen);
CREATE INDEX IF NOT EXISTS ix_source    ON postings(source);
-- ix_identity, ix_role, ix_sector, ix_mode and ix_state are created in Store._migrate()
-- instead: this script also runs against databases predating those columns,
-- where CREATE TABLE IF NOT EXISTS is a no-op and the index would fail.

CREATE TABLE IF NOT EXISTS seen (
    key         TEXT PRIMARY KEY,
    disposition TEXT NOT NULL DEFAULT 'new',
    first_seen  TEXT NOT NULL DEFAULT '',
    last_seen   TEXT NOT NULL DEFAULT '',
    marked_at   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS budget (
    api      TEXT NOT NULL,
    month    TEXT NOT NULL,
    requests INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (api, month)
);
CREATE TABLE IF NOT EXISTS budget_limit (
    api   TEXT PRIMARY KEY,
    limit_requests INTEGER NOT NULL
);

-- Call timestamps for sources that are rate-limited by politeness rather
-- than by a quota. Kept in the database, not in memory, so the limit holds
-- across separate invocations — which is the only way it is ever used.
CREATE TABLE IF NOT EXISTS rate (
    source TEXT NOT NULL,
    ts     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rate ON rate(source, ts);

CREATE TABLE IF NOT EXISTS watchlist (
    employer   TEXT PRIMARY KEY,
    board_url  TEXT NOT NULL DEFAULT '',
    platform   TEXT NOT NULL DEFAULT '',
    added_at   TEXT NOT NULL DEFAULT '',
    added_via  TEXT NOT NULL DEFAULT ''
);

-- Append-only: what a flat log would have given us, kept deliberately.
CREATE TABLE IF NOT EXISTS history (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    key    TEXT NOT NULL,
    ts     TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    event  TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_hist_key ON history(key);
"""


def now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def month(ts=None):
    return (ts or now())[:7]


# ---------------------------------------------------------------------------
# Dedup key
# ---------------------------------------------------------------------------

LEGAL = re.compile(
    r"\b(inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|plc|gmbh|"
    r"s\.a|n\.v|pty|llp|the)\b\.?", re.I)
PUNCT = re.compile(r"[^\w\s]+", re.U)
WS = re.compile(r"\s+")

ATS_ID = [
    (re.compile(r"boards\.greenhouse\.io/[^/]+/jobs/(\d+)"), "gh"),
    (re.compile(r"[?&]gh_jid=(\d+)"), "gh"),
    (re.compile(r"jobs\.lever\.co/[^/]+/([0-9a-f-]{36})", re.I), "lever"),
    (re.compile(r"jobs\.ashbyhq\.com/[^/]+/([0-9a-f-]{36})", re.I), "ashby"),
    (re.compile(r"myworkdayjobs\.com/.*?(JR[-_]?\d+)", re.I), "wd"),
    (re.compile(r"\b(R\d{6,})\b"), "req"),
    (re.compile(r"icims\.com/jobs/(\d{4,})"), "icims"),
    (re.compile(r"smartrecruiters\.com/[^/]+/(\d{8,})"), "sr"),
    (re.compile(r"linkedin\.com/jobs/view/(?:.*?-)?(\d{8,})"), "li"),
    (re.compile(r"indeed\.com/.*?[?&]jk=([0-9a-f]{10,})", re.I), "indeed"),
    (re.compile(r"usajobs\.gov/job/(\d{6,})"), "usajobs"),
]


def norm(s):
    """Casefold, strip accents, drop legal suffixes and punctuation."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = LEGAL.sub(" ", s.casefold())
    s = PUNCT.sub(" ", s)
    return WS.sub(" ", s).strip()


def slug(value, limit=60):
    """Filesystem-safe name. Same rules as fetch_posting.slug, deliberately.

    A job fetched from its URL and the same job briefed out of the corpus
    must land in the same directory name, or resuming an interrupted batch
    with `--on-exist skip` would tailor it twice under two spellings.
    """
    t = (value or "").lower().encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    if len(t) > limit:
        cut = t[:limit]
        if "-" in cut and cut.rindex("-") >= limit // 2:
            cut = cut[:cut.rindex("-")]
        t = cut
    return t.strip("-") or "unknown"


def norm_location(s):
    parts = [norm(p) for p in re.split(r"[,/|]", s or "") if norm(p)]
    drop = {"united states", "us", "usa", "united states of america", "remote"}
    parts = [p for p in parts if p not in drop]
    return " ".join(parts[:2])


def ats_key(url):
    """`<ats>:<id>` when the URL carries a recognisable requisition id."""
    if not url:
        return None
    for pat, tag in ATS_ID:
        m = pat.search(url)
        if m:
            return f"{tag}:{m.group(1).upper().replace('_', '-')}"
    return None


def posting_key(rec):
    """The §5 dedup key: ATS id when available, else normalised identity.

    The identity fallback deliberately excludes the URL. The same job arrives
    from several tiers under several URLs, and an employer comes back under
    several spellings ("University of Illinois Chicago", "University of
    Illinois - Chicago"), so the employer is normalised rather than matched.
    """
    for field in ("apply_url", "url"):
        k = ats_key(rec.get(field))
        if k:
            return k
    req = (rec.get("req_id") or "").strip()
    company = norm(rec.get("company"))
    if req and company:
        return f"req:{company[:24]}:{req.upper()}"
    ident = "|".join((company, norm(rec.get("title")),
                      norm_location(rec.get("location"))))
    return "id:" + hashlib.sha1(ident.encode()).hexdigest()[:16]


def identity(rec):
    """Normalised (employer, title, location) — stable across reposts.

    posting_key() prefers the ATS/board id in the URL because it is exact. But
    a board can re-advertise the same job under a new id (LinkedIn does this
    routinely), and then the key changes while the job has not. This is the
    fallback identity, computed for every record so reposts can be linked.
    """
    ident = "|".join((norm(rec.get("company")), norm(rec.get("title")),
                      norm_location(rec.get("location"))))
    return hashlib.sha1(ident.encode()).hexdigest()[:16]


ROLE_PATTERNS = [
    ("postdoc",      r"post[\s-]?doc|postdoctoral|research fellow"),
    ("grad_student", r"\bph\.?d\.?\s+(student|position|candidate|researcher)|"
                     r"graduate (research |teaching )?assistant|\bgrad student\b"),
    ("faculty",      r"\bprofessor\b|\bfaculty\b|tenure[\s-]?track|"
                     r"\bendowed chair\b|\bdepartment chair\b"),
    ("lecturer",     r"\blecturer\b|\binstructor\b|\badjunct\b|\bteaching\b"),
    ("intern",       r"\bintern\b|\binternship\b|\bco-?op\b|\bsummer student\b"),
    ("management",   r"\b(director|head of|chief|vice president|\bvp\b|manager|"
                     r"supervisor|principal investigator)\b"),
    ("research",     r"research (scientist|associate|engineer|staff|specialist|"
                     r"technologist)|\bscientist\b|computational|\bmodeling\b|"
                     r"\b(physicist|chemist|biologist|mathematician|researcher|"
                     r"metallurgist|crystallographer|spectroscopist)\b"),
    ("engineering",  r"\bengineer\b|\bdeveloper\b|\bprogrammer\b|\barchitect\b|"
                     r"\bsoftware\b"),
    ("data",         r"data scientist|machine learning|\bml engineer\b|\bai\b|"
                     r"\banalyst\b|\bstatistician\b"),
    ("technician",   r"\btechnician\b|\boperator\b|\bcoordinator\b|"
                     r"\b(lab|laboratory|office|program|administrative|research)"
                     r"\s+assistant\b"),
]
ROLE_RE = [(name, re.compile(pat, re.I)) for name, pat in ROLE_PATTERNS]

SECTOR_PATTERNS = [
    ("national_lab", r"national (laboratory|lab)\b|applied physics laborator|"
                     r"university affiliated research center|"
                     r"argonne|sandia|los alamos|"
                     r"livermore|oak ridge|brookhaven|fermi|pacific northwest|"
                     r"idaho national|renewable energy laboratory|\bslac\b|"
                     r"jet propulsion|\blanl\b|\bllnl\b|\bornl\b|\bpnnl\b|"
                     r"\bnrel\b|\banl\b|\bbnl\b|\binl\b"),
    ("government",   r"\bnasa\b|\bnist\b|\bnih\b|\bnsf\b|\bnoaa\b|\busda\b|"
                     r"department of (energy|defense|commerce|health)|"
                     r"\bu\.?s\.? (army|navy|air force|geological)|federal\b"),
    ("comm_college", r"community college|\bcollege of du ?page\b|"
                     r"\b(harper|moraine|oakton|triton|elgin) college\b"),
    ("university",   r"universit|\bcollege\b|institute of technology|"
                     r"\bschool of\b|\bacademy\b|\bpolytechnic\b"),
    ("nonprofit",    r"\bfoundation\b|\bresearch institute\b|\bsociety\b|"
                     r"\bmuseum\b|\bhospital\b|\bmedical center\b"),
]
SECTOR_RE = [(name, re.compile(pat, re.I)) for name, pat in SECTOR_PATTERNS]


def role_class(title, text=""):
    """Coarse track for a posting: postdoc, faculty, research, engineering...

    Title only, except that a blank title falls back to the opening of the
    body. Ordered, first match wins: "Postdoctoral Research Associate" is a
    postdoc, not research staff, so the specific patterns come first.
    """
    hay = (title or "") or (text or "")[:200]
    for name, pat in ROLE_RE:
        if pat.search(hay):
            return name
    return "other"


def sector_of(company):
    """Coarse employer type. A guess from the name, overridable by hand."""
    name = company or ""
    for sec, pat in SECTOR_RE:
        if pat.search(name):
            return sec
    return "company" if name else ""


# ---------------------------------------------------------------------------
# Work mode, place and work-authorisation gates
#
# All three are read out of text the record already carries, at insert time,
# into columns `select` can filter on in SQL. The alternative — scanning every
# body on every run — is the thing role_class/sector exist to avoid, and the
# authorisation gates are the filters most likely to be on by default, so they
# are the ones least affordable as a full-text scan.
#
# Every pattern here is a heuristic over prose written by someone who was not
# thinking about being parsed. They are recomputable (`reclassify`) precisely
# because they will need editing, and a wrong one is corrected by hand with
# `tag`, which `reclassify` never overwrites.
# ---------------------------------------------------------------------------

HYBRID_RE = re.compile(
    r"\bhybrid\b|partially remote|remote[- ]?friendly|flexible (work )?location|"
    r"\d\s*(days?)\s*(a|per)?\s*week[^.]{0,30}(on[- ]?site|in[- ]?office|"
    r"in the office)|(on[- ]?site|in[- ]?office)[^.]{0,20}\d\s*days?\s*(a|per)\s*week",
    re.I)
# A bare "remote" is a reliable signal in a title or a location field and a
# trap in a body: "RPC (Remote Procedure Call)" in a skills list had an
# Argonne bench job reading as remote. The body therefore needs a phrase that
# can only be about where the work happens.
REMOTE_RE = re.compile(
    r"\bremote\b|work from home|work[- ]from[- ]anywhere|telecommut|telework|"
    r"\bvirtual (position|role)\b",
    re.I)
REMOTE_STRONG_RE = re.compile(
    r"\b(fully|100%|completely|entirely)[\s-]*remote\b|"
    r"remote[- ](position|role|work|job|opportunity|employee|first)\b|"
    r"(position|role|job|work) is (fully |100% )?remote\b|"
    r"work(ing)? remotely\b|\bremote \(u\.?s\.?\)|"
    r"work from home|work[- ]from[- ]anywhere|telecommut|telework|"
    r"\bvirtual (position|role)\b",
    re.I)
ONSITE_RE = re.compile(
    r"\bon[- ]?site\b|\bonsite\b|\bin[- ]person\b|\bin[- ]office\b|"
    r"\bnot (a )?remote\b|no remote work|must (be able to )?relocate",
    re.I)

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "washington dc": "DC", "washington d c": "DC",
    "puerto rico": "PR", "guam": "GU", "virgin islands": "VI",
}
STATE_CODES = set(STATES.values())
# "DC" is both a city and a code; "Washington, DC" is resolved by the comma
# split, not here. A bare two-letter token is read as a US state even when it
# is also a country code — "Tel Aviv, IL" reads as Illinois. Left deliberately:
# the sources are US job boards that spell out "Israel", and the guard that
# would fix it ("only trust a code with another US signal nearby") would break
# "Chicago, IL", which is the overwhelmingly common case.
COUNTRIES = {
    "united states": "US", "usa": "US", "u s a": "US", "u s": "US", "us": "US",
    "canada": "CA", "united kingdom": "GB", "uk": "GB", "england": "GB",
    "scotland": "GB", "germany": "DE", "france": "FR", "switzerland": "CH",
    "netherlands": "NL", "sweden": "SE", "denmark": "DK", "norway": "NO",
    "australia": "AU", "india": "IN", "china": "CN", "japan": "JP",
    "singapore": "SG", "israel": "IL", "ireland": "IE", "spain": "ES",
    "italy": "IT", "belgium": "BE", "austria": "AT", "finland": "FI",
    "poland": "PL", "mexico": "MX", "brazil": "BR", "south korea": "KR",
}
ZIP_RE = re.compile(r"\b\d{5}(-\d{4})?\b")


def place_of(location):
    """(state, country) from a free-text location. ('', '') when unreadable.

    Location strings arrive as "Chicago, IL", "Chicago, IL 60607",
    "Illinois, United States", "Remote (US)", "Lemont, Illinois, United
    States" and worse. Split on the separators, resolve each field against
    the state and country tables, and take the first of each that answers.
    """
    raw = ZIP_RE.sub(" ", location or "")
    parts = [norm(p) for p in re.split(r"[,/|()\u2022]|\s+-\s+", raw)]
    parts = [p for p in parts if p]
    state = country = ""
    # Two-letter codes first, across every field: "Washington, DC" is DC, and
    # resolving left to right would call it WA.
    for p in parts:
        if len(p) == 2 and p.upper() in STATE_CODES and p != "us":
            state = p.upper()
            break
    for p in parts:
        if not state and p in STATES:
            state = STATES[p]
        if not country and p in COUNTRIES:
            country = COUNTRIES[p]
    if state and not country:
        country = "US"          # a USPS code is only ever a US state.
    return state, country


def work_mode_of(rec_remote, title, location, text):
    """remote | hybrid | onsite | '' — the three-way the boolean cannot make.

    Hybrid is tested first: a hybrid posting says "remote" too, and calling it
    remote is the error that wastes an application. `onsite` is also the
    answer when a posting names a physical place and says nothing about
    working away from it, which is how almost every onsite job is written.
    """
    hay = " ".join([title or "", location or "", text or ""])
    if HYBRID_RE.search(hay):
        return "hybrid"
    if rec_remote or REMOTE_RE.search(" ".join([title or "", location or ""])):
        return "remote"
    if REMOTE_STRONG_RE.search(text or ""):
        # The body says so but the title and location do not. Trust it only
        # when nothing contradicts it.
        return "onsite" if ONSITE_RE.search(text or "") else "remote"
    if ONSITE_RE.search(hay):
        return "onsite"
    state, _ = place_of(location)
    return "onsite" if (state or (location or "").strip()) else ""


# Every pattern that matches is recorded, and a posting can legitimately
# carry both `no_visa_sponsor` and `visa_sponsor_ok` — large employers say
# both, in different paragraphs, about different reqs.
#
# The patterns are deliberately loose, because the phrasings measured on real
# postings are endlessly varied ("proof of U.S. citizenship", "Eligibility
# requirements include U.S. citizenship", "U.S. Citizenship with the ability
# to obtain a clearance" — one requirement, three sentences with no shared
# structure). What keeps loose patterns honest is VETO_RE below.
AUTH_PATTERNS = [
    ("citizen",       r"\bu\.?\s?s\.?\s?citizen(ship|s)?\b|"
                      r"\bunited states citizen(ship|s)?\b|"
                      r"\bcitizenship (is )?(required|mandatory)\b"),
    ("citizen_or_pr", r"citizens?(hip)? or (lawful )?permanent resident|"
                      r"citizens? or green card|"
                      r"permanent resident(s|cy)? (status )?(is )?required|"
                      r"\bgreen card holder|\bu\.?s\.? persons?\b"),
    # Every alternative here contains the word "clearance" or is unambiguous
    # on its own (TS/SCI). A bare "secret" does not qualify: "our secret to
    # success is a collaborative culture" is a sentence in real postings, and
    # matching it would silently hide the job under --auth-exclude clearance.
    ("clearance",     r"security clearance|\bts/sci\b|"
                      r"\bq[\s\-\"']{0,3}clearance\b|\bl[\s\-\"']{0,3}clearance\b|"
                      r"\bdoe clearance\b|active clearance|"
                      r"clearance (is |will be )?(required|mandatory)|"
                      r"(obtain|maintain|hold|possess)[^.]{0,30}clearance|"
                      r"\b(secret|top[\s-]secret|interim|public trust)\b"
                      r"[^.]{0,25}clearance|"
                      r"clearance[^.]{0,25}\b(secret|top[\s-]secret)\b"),
    ("export_ctrl",   r"\bitar\b|export[\s-]control|"
                      r"export administration regulations|deemed export"),
    ("no_visa_sponsor", r"(not|unable|cannot|will not|does not|do not)[^.]{0,40}"
                      r"sponsor|"
                      r"\bno (visa |work )?sponsorship\b|"
                      r"sponsorship (is )?not (available|offered|provided)|"
                      r"without (the )?(need for )?(current or future |"
                      r"now or in the future )?sponsorship|"
                      r"not (require|need) sponsorship"),
    # Written so the denials above cannot match it in passing: "unable to
    # sponsor" contains "able to sponsor", and "unable to provide visa
    # sponsorship for this position" contains "visa sponsorship for".
    ("visa_sponsor_ok", r"sponsorship (is |will be )?(available|offered|provided|"
                      r"possible)|\b(we|will|do|does|can) sponsor\b|"
                      r"(happy|willing|prepared|open) to sponsor|"
                      r"h[\s-]?1b sponsorship"),
    ("no_f1opt",      r"\b(opt|cpt)\b[^.]{0,40}not (accepted|eligible|considered)|"
                      r"\bno (opt|cpt)\b|"
                      r"(cannot|unable to|do not) (accept|consider)[^.]{0,30}"
                      r"\b(opt|cpt)\b"),
]
AUTH_RE = [(name, re.compile(pat, re.I)) for name, pat in AUTH_PATTERNS]
AUTH_NAMES = [n for n, _ in AUTH_PATTERNS]

# Near-identical words appear in the EEO paragraph of almost every posting
# ("without regard to ... citizenship status"), where they mean the opposite
# of a requirement. A match surrounded by any of these is thrown away.
VETO_RE = re.compile(
    r"regardless of|without regard to|does not discriminate|"
    r"equal (employment )?opportunity|affirmative action|"
    r"not required|no clearance|protected veteran", re.I)
VETO_WINDOW = 150

# `visa_sponsor_ok` is the one tag whose patterns are polarity-blind: "sponsorship
# is available" and "no visa sponsorship is available" differ by one word
# before the match, and "H-1B sponsorship" appears verbatim in both an offer
# and a refusal. Anything matching it is re-checked against the clause it
# sits in — the clause, not a fixed window, so "Relocation is not provided.
# Sponsorship is available." stays an offer.
NEGATABLE = {"visa_sponsor_ok"}
NEG_RE = re.compile(
    r"\b(no|not|non|never|unable|cannot|can'?t|won'?t|will not|does not|"
    r"doesn'?t|do not|without|ineligible|unwilling|neither|nor)\b", re.I)
CLAUSE_BREAKS = ".;!?\n"


def _clause_before(hay, pos, limit=90):
    """The text from the last clause boundary up to `pos`."""
    chunk = hay[max(0, pos - limit):pos]
    cut = max(chunk.rfind(c) for c in CLAUSE_BREAKS)
    return chunk[cut + 1:] if cut >= 0 else chunk
# "or permanent resident" turns a citizenship clause into a weaker gate, and
# a filter hiding citizens-only postings must not hide this one.
PR_SOFTENER = re.compile(
    r"citizens?(hip)? or (lawful )?permanent resident|citizens? or green card",
    re.I)


def auth_of(text, title=""):
    """Comma-joined work-authorisation gates stated in the posting.

    Read from the posting's own words, never from anything about the user:
    this column says what the employer demands, and whether that rules the
    user out is answered later, locally, by a filter the user set (§2c). A
    record with no body yields '' — absence of a gate here means "not stated
    in the text we hold", not "no gate".
    """
    hay = " ".join([title or "", text or ""])
    if not hay.strip():
        return ""
    found = []
    for name, pat in AUTH_RE:
        for m in pat.finditer(hay):
            lo = max(0, m.start() - VETO_WINDOW)
            if VETO_RE.search(hay[lo:m.end() + VETO_WINDOW]):
                continue        # EEO boilerplate, not a requirement
            if name in NEGATABLE and NEG_RE.search(_clause_before(hay, m.start())):
                continue        # a denial, not an offer
            found.append(name)
            break
    if "citizen" in found and PR_SOFTENER.search(hay):
        found.remove("citizen")
    return ",".join(found)


TAG_OK = re.compile(r"[^a-z0-9_.-]+")


def clean_tags(values):
    """Normalise free-form tags: lowercase, punctuation to '-', deduped."""
    out = []
    for v in values or ():
        for part in str(v).split(","):
            t = TAG_OK.sub("-", part.strip().casefold()).strip("-")
            if t and t not in out:
                out.append(t)
    return sorted(out)


def derived(rec):
    """The filter columns read out of one record: work_mode, state, country, auth.

    One function so `append` (on insert) and `reclassify` (over the corpus)
    cannot drift apart — the second exists precisely to re-run the first.
    """
    state, country = place_of(rec.get("location"))
    return {"work_mode": work_mode_of(rec.get("remote"), rec.get("title"),
                                      rec.get("location"), rec.get("text")),
            "state": state, "country": country,
            "auth": auth_of(rec.get("text"), rec.get("title"))}


# ---------------------------------------------------------------------------
# Profile similarity
# ---------------------------------------------------------------------------

TOKEN = re.compile(r"[a-z][a-z0-9+#.\-]+")
STOP = set("""
the and for with that this from are was were you your our their its has have
had will would can could should may might must are not but all any each other
who whom which what when where how why into onto than then them they there here
been being does did done such very more most some only own same too also about
above below under over out off per via within without across among between
job jobs position positions role roles work working opportunity opportunities
experience experiences required requirement requirements preferred qualified
qualifications candidate candidates applicant applicants apply application
employer employment equal opportunity diversity inclusion veteran disability
status benefits salary range compensation full time part time degree years
ability skills knowledge including include includes team teams support
""".split())


def tokens(text):
    return [t for t in TOKEN.findall((text or "").casefold())
            if len(t) > 2 and t not in STOP]


def profile_text(path):
    """Every string in profile.json, flattened. Shape-agnostic on purpose."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""
    out = []

    def walk(node):
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
    walk(data)
    return " ".join(out)


def similarity(query, docs):
    """Cosine of TF-IDF vectors: {key: score} for `docs` [(key, text)].

    IDF is computed over the candidate set itself, so a term every posting
    shares ("laboratory" in a run of lab jobs) stops carrying signal and the
    ranking turns on what actually distinguishes one posting from another.
    Scores are therefore comparable within a run, not across runs.
    """
    import math
    from collections import Counter
    doc_tf, df = [], Counter()
    for key, text in docs:
        tf = Counter(tokens(text))
        doc_tf.append((key, tf))
        df.update(tf)
    n = len(docs) or 1
    idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
    unseen = math.log(n + 1) + 1.0
    qtf = Counter(tokens(query))
    qvec = {t: (1 + math.log(f)) * idf.get(t, unseen) for t, f in qtf.items()}
    qnorm = math.sqrt(sum(v * v for v in qvec.values())) or 1.0
    out = {}
    for key, tf in doc_tf:
        vec = {t: (1 + math.log(f)) * idf[t] for t, f in tf.items()}
        dnorm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        dot = sum(v * qvec[t] for t, v in vec.items() if t in qvec)
        out[key] = round(dot / (qnorm * dnorm), 4)
    return out


def _set_clause(column, values):
    """`(','||col||',') LIKE '%,v,%'` — one row's set membership, OR-ed.

    `auth` and `tags` hold comma-joined sets in one column. Matching them
    with a bare LIKE would make `citizen` match `citizen_or_pr`, so both ends
    are padded with the delimiter before the comparison.
    """
    frag = " OR ".join([f"(','||{column}||',') LIKE ?"] * len(values))
    return "(" + frag + ")", [f"%,{v},%" for v in values]


def _age_days(ts):
    if not ts:
        return None
    try:
        then = _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=_dt.timezone.utc)
    except ValueError:
        return None
    return (_dt.datetime.now(_dt.timezone.utc) - then).days


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.path = os.path.join(root, DB_NAME)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self):
        """Add columns the schema gained after this database was created."""
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(postings)")}
        for col, decl in (("identity", "TEXT NOT NULL DEFAULT ''"),
                          ("repost_of", "TEXT NOT NULL DEFAULT ''"),
                          ("repost_count", "INTEGER NOT NULL DEFAULT 0"),
                          ("first_posted", "TEXT NOT NULL DEFAULT ''"),
                          ("role_class", "TEXT NOT NULL DEFAULT ''"),
                          ("sector", "TEXT NOT NULL DEFAULT ''"),
                          ("work_mode", "TEXT NOT NULL DEFAULT ''"),
                          ("state", "TEXT NOT NULL DEFAULT ''"),
                          ("country", "TEXT NOT NULL DEFAULT ''"),
                          ("auth", "TEXT NOT NULL DEFAULT ''"),
                          ("tags", "TEXT NOT NULL DEFAULT ''")):
            if col not in have:
                self.db.execute(f"ALTER TABLE postings ADD COLUMN {col} {decl}")
        # Verdict caching was removed: a stored judgement went stale the
        # moment the profile changed and nothing could tell that it had.
        # body_pruned went with the pruning mechanism it existed to flag.
        self.db.execute("DROP INDEX IF EXISTS ix_score")
        for dead in ("score", "judged_at", "judgment", "judge_note",
                     "profile_fp", "body_pruned"):
            if dead in have:
                try:
                    self.db.execute(f"ALTER TABLE postings DROP COLUMN {dead}")
                except sqlite3.OperationalError:
                    pass  # SQLite < 3.35; the column is simply ignored.
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_identity ON postings(identity)")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_role ON postings(role_class)")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_sector ON postings(sector)")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_mode ON postings(work_mode)")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_state ON postings(state)")
        # Backfill identity for rows written before the column existed.
        for row in self.db.execute(
                "SELECT key, company, title, location FROM postings "
                "WHERE identity=''").fetchall():
            self.db.execute("UPDATE postings SET identity=? WHERE key=?",
                            (identity(dict(row)), row["key"]))
        # One pass covers every derived column, so a database missing any of
        # them is brought fully up to date at once.
        if "role_class" not in have or "work_mode" not in have:
            self.reclassify()
        elif self.db.execute(
                "SELECT 1 FROM postings WHERE (','||auth||',') LIKE '%,no_sponsor,%'"
                " OR (','||auth||',') LIKE '%,sponsor_ok,%'"
                " OR (','||auth||',') LIKE '%,no_opt,%' LIMIT 1").fetchone():
            # Renamed 2026-10-23: no_sponsor/sponsor_ok/no_opt became
            # no_visa_sponsor/visa_sponsor_ok/no_f1opt, because "sponsor" alone
            # reads as funding in a research posting and "OPT" means nothing to
            # anyone who has not held an F-1. The column is derived, so the
            # rename is a re-derive, not a data migration.
            self.reclassify()

    def close(self):
        self.db.commit()
        self.db.close()

    # save() is kept so callers need not care that writes are transactional.
    def save(self):
        self.db.commit()

    # -- corpus -----------------------------------------------------------
    def get(self, key):
        row = self.db.execute("SELECT * FROM postings WHERE key=?", (key,)).fetchone()
        return _row_to_rec(row) if row else None

    def known(self, key):
        """True when the corpus already holds a usable body for this key."""
        row = self.db.execute(
            "SELECT length(text) AS n FROM postings WHERE key=?", (key,)).fetchone()
        return bool(row and row["n"])

    def known_many(self, keys):
        if not keys:
            return {}
        out = {k: False for k in keys}
        for chunk in (keys[i:i + 500] for i in range(0, len(keys), 500)):
            q = ",".join("?" * len(chunk))
            for row in self.db.execute(
                    f"SELECT key, length(text) AS n FROM postings WHERE key IN ({q})",
                    chunk):
                out[row["key"]] = bool(row["n"])
        return out

    def _same_posting(self, key, rec):
        """Is the row already stored under `key` the same job as `rec`?

        Only ever asked about `id:` keys — the weak fallback in posting_key()
        that hashes employer|title|location and deliberately ignores the URL.
        That fallback cannot tell two genuinely different reqs apart: one lab
        advertising "Postdoctoral Appointee" in two divisions on the same day
        hashes to one key, and merging them loses a real job silently. ATS ids
        and `req:` keys are exact and never reach this.

        Returns True for a free slot, so callers can use it to find one.
        """
        row = self.db.execute(
            "SELECT text, apply_url, url FROM postings WHERE key=?",
            (key,)).fetchone()
        if row is None:
            return True
        old = (row["text"] or "").strip()
        new = (rec.get("text") or "").strip()
        if not old or not new:
            # Nothing to compare on. A sighting that fills an empty body is an
            # enrichment, not a different job; treat it as the same.
            return True
        # Word sequences, not word sets. Two different postings from one
        # employer share a boilerplate header and footer, so their vocabularies
        # overlap heavily while the role description in the middle differs
        # completely; a set metric reads that as the same job. Matching blocks
        # measure how much of the shorter text appears in the longer one *in
        # order*, which separates "truncated copy of the same posting" from
        # "same boilerplate, different role".
        a = re.findall(r"[a-z0-9]+", old.lower())[:1500]
        b = re.findall(r"[a-z0-9]+", new.lower())[:1500]
        if not a or not b:
            return True
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        overlap = (sum(blk.size for blk in sm.get_matching_blocks())
                   / float(min(len(a), len(b))))
        # Two different URLs are positive evidence of two listings, so the bar
        # to call them one job goes up. The cross-tier case this protects —
        # an aggregator's shortened copy of a posting also read from the
        # employer — still clears it, because the short one is near-contiguous
        # inside the long one.
        old_url = (row["apply_url"] or row["url"] or "").strip().lower()
        new_url = (rec.get("apply_url") or rec.get("url") or "").strip().lower()
        differing_urls = bool(old_url and new_url and old_url != new_url)
        return overlap >= (0.85 if differing_urls else 0.6)

    def append(self, recs, source, status="open"):
        """Write records through.

        Returns {added, updated, unchanged, split, keys}. `keys` is the key
        each record actually landed under, in input order — not what
        posting_key() would recompute, which is wrong for anything that
        split. The caller marks records by that key, so handing back the
        pre-split one would make `mark` silently miss.

        A later sighting never downgrades a better record: an aggregator
        re-sighting of a job already read from the employer's own board
        refreshes last_seen and seen_via but leaves the body alone.
        """
        ts = now()
        added = updated = unchanged = split = 0
        used = []
        for rec in recs:
            rec = dict(rec)
            key = rec.get("key") or posting_key(rec)
            # A weak key that already holds a different job gets a suffix
            # rather than overwriting it. Never drop a posting on a hash
            # collision: a dropped job is invisible, a duplicated one is not.
            did_split = False
            if key.startswith("id:") and not self._same_posting(key, rec):
                base, n = key, 2
                while not self._same_posting("%s#%d" % (base, n), rec):
                    n += 1
                key = "%s#%d" % (base, n)
                split += 1
                did_split = True
            used.append(key)
            src = rec.get("source") or source
            tier = TIER.get(src, 0)
            prev = self.db.execute(
                "SELECT tier, length(text) AS n, seen_via, first_seen, status "
                "FROM postings WHERE key=?", (key,)).fetchone()

            ident = identity(rec)
            # A repost is the same identity under a different key. The earliest
            # row wins as the canonical one; later ones point at it and the
            # caller can choose not to resurface them.
            repost_of, repost_n = "", 0
            # A split record shares its twin's identity by construction — that
            # is what made them collide. Letting the repost check see it files
            # the second job as a repost of the first, and select() hides
            # repost_of!='' by default, so the job we just went to the trouble
            # of keeping would never appear in a shortlist.
            if prev is None and ident and not did_split:
                twin = self.db.execute(
                    "SELECT key, repost_of, repost_count, first_posted, first_seen "
                    "FROM postings WHERE identity=? ORDER BY first_seen LIMIT 1",
                    (ident,)).fetchone()
                if twin:
                    repost_of = twin["repost_of"] or twin["key"]
                    self.db.execute(
                        "UPDATE postings SET repost_count=repost_count+1 WHERE key=?",
                        (repost_of,))
                    repost_n = (twin["repost_count"] or 0) + 1

            seen_via = set(rec.get("seen_via") or []) | {src}
            if prev:
                seen_via |= set(json.loads(prev["seen_via"] or "[]"))
                first_seen = prev["first_seen"] or ts
                better = (tier, len(rec.get("text") or "")) >= (prev["tier"], prev["n"])
            else:
                first_seen = ts
                better = True

            vals = {f: (rec.get(f) or "") for f in POSTING_FIELDS}
            vals.update(
                key=key, company_norm=norm(rec.get("company")),
                remote=int(bool(rec.get("remote"))), source=src, tier=tier,
                seen_via=json.dumps(sorted(seen_via)), query=rec.get("query") or "",
                first_seen=first_seen, last_seen=ts,
                status=rec.get("status") or status, status_at=ts,
                text_origin=rec.get("text_origin") or
                ("canonical" if src in ("direct", "usajobs", "manual")
                 else "aggregator"),
                identity=ident,
                role_class=role_class(rec.get("title"), rec.get("text")),
                sector=sector_of(rec.get("company")),
                **derived(rec))

            if prev is None:
                vals["repost_of"] = repost_of
                vals["first_posted"] = rec.get("posted_on") or ts
                cols = ",".join(vals)
                self.db.execute(
                    f"INSERT INTO postings ({cols}) VALUES ({','.join('?' * len(vals))})",
                    list(vals.values()))
                added += 1
                self._log(key, ts, src, "repost" if repost_of else "added",
                          repost_of or rec.get("title", ""))
            elif better:
                # `tags` is deliberately not in vals — it is hand-applied and
                # a fresher sighting from a source knows nothing about it.
                sets = ",".join(f"{c}=?" for c in vals if c != "key")
                self.db.execute(f"UPDATE postings SET {sets} WHERE key=?",
                                [v for c, v in vals.items() if c != "key"] + [key])
                updated += 1
                self._log(key, ts, src, "updated", "")
            else:
                # Keep the better body; record that a weaker tier saw it again.
                self.db.execute(
                    "UPDATE postings SET last_seen=?, seen_via=? WHERE key=?",
                    (ts, json.dumps(sorted(seen_via)), key))
                unchanged += 1
                self._log(key, ts, src, "reseen", "")

            self.db.execute(
                "INSERT INTO seen (key, disposition, first_seen, last_seen) "
                "VALUES (?,'new',?,?) "
                "ON CONFLICT(key) DO UPDATE SET last_seen=excluded.last_seen",
                (key, first_seen, ts))
        self.db.commit()
        return {"added": added, "updated": updated, "unchanged": unchanged,
                "split": split, "keys": used}

    def _log(self, key, ts, source, event, detail=""):
        self.db.execute(
            "INSERT INTO history (key, ts, source, event, detail) VALUES (?,?,?,?,?)",
            (key, ts, source, event, detail[:200]))

    def find(self, employer=None, status=None, source=None, since_days=None,
             disposition=None, limit=200, with_text=False, roles=(), sectors=(),
             work_modes=(), states=(), tags=()):
        q = ["SELECT p.* FROM postings p"]
        where, args = [], []
        if disposition:
            q.append("JOIN seen s ON s.key = p.key")
            where.append("s.disposition=?")
            args.append(disposition)
        if employer:
            where.append("p.company_norm LIKE ?")
            args.append(f"%{norm(employer)}%")
        if status:
            where.append("p.status=?")
            args.append(status)
        if source:
            where.append("p.source=?")
            args.append(source)
        if roles:
            where.append("p.role_class IN (%s)" % ",".join("?" * len(roles)))
            args += list(roles)
        if sectors:
            where.append("p.sector IN (%s)" % ",".join("?" * len(sectors)))
            args += list(sectors)
        if work_modes:
            where.append("p.work_mode IN (%s)" % ",".join("?" * len(work_modes)))
            args += list(work_modes)
        if states:
            where.append("p.state IN (%s)" % ",".join("?" * len(states)))
            args += [x.upper() for x in states]
        for t in tags:
            frag, a = _set_clause("p.tags", [t])
            where.append(frag)
            args += a
        if since_days is not None:
            cutoff = (_dt.datetime.now(_dt.timezone.utc)
                      - _dt.timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            where.append("p.last_seen>=?")
            args.append(cutoff)
        if where:
            q.append("WHERE " + " AND ".join(where))
        q.append("ORDER BY p.posted_on DESC, p.last_seen DESC LIMIT ?")
        args.append(limit)
        rows = self.db.execute(" ".join(q), args).fetchall()
        return [_row_to_rec(r, with_text) for r in rows]

    def mark(self, key, disposition):
        if disposition not in DISPOSITIONS:
            raise SystemExit(f"disposition must be one of {', '.join(DISPOSITIONS)}")
        # A key with no posting behind it is a typo or a stale key, never an
        # intention. Accepting it wrote a phantom `seen` row, printed success
        # and exited 0, while the posting the caller meant stayed unmarked —
        # so it resurfaced in the next shortlist and got tailored twice, with
        # nothing in the transcript to suggest anything had gone wrong.
        if self.db.execute("SELECT 1 FROM postings WHERE key=?",
                           (key,)).fetchone() is None:
            raise ValueError(
                "no posting with key %r. Use the key `select`, `brief` or "
                "`ingest` reported for this record — a record that split off "
                "a key collision lives under a `#2` suffix." % key)
        ts = now()
        self.db.execute(
            "INSERT INTO seen (key, disposition, first_seen, last_seen, marked_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
            "disposition=excluded.disposition, marked_at=excluded.marked_at",
            (key, disposition, ts, ts, ts))
        self._log(key, ts, "", "disposition", disposition)
        self.db.commit()

    def tag(self, key, add=(), remove=(), clear=False):
        """Hand-applied labels on one posting. Returns the resulting set.

        The escape hatch for everything the patterns cannot derive: a gate
        phrased in a way `auth_of` misses, a lab's internal name for a team,
        "ask Priya about this one". `reclassify` never touches it, and a
        fresher sighting from a source never overwrites it.
        """
        row = self.db.execute(
            "SELECT tags FROM postings WHERE key=?", (key,)).fetchone()
        if row is None:
            raise SystemExit(f"no record for {key}")
        cur = [] if clear else [t for t in (row["tags"] or "").split(",") if t]
        drop = set(clean_tags(remove))
        cur = sorted((set(cur) - drop) | set(clean_tags(add)))
        self.db.execute("UPDATE postings SET tags=? WHERE key=?",
                        (",".join(cur), key))
        self._log(key, now(), "", "tagged", ",".join(cur))
        self.db.commit()
        return cur

    def sweep_end(self, source, employer=None, stale_after_days=30, run_start=None):
        """Close out a completed sweep.

        A direct board sweep is authoritative: a job it did not return this run
        is closed. The metered tiers cannot tell "gone" from "not matched by
        this query", so their records only ever go stale.
        """
        ts = now()
        authoritative = source in ("direct", "usajobs")
        if authoritative and not run_start:
            # Without a run start there is no sweep, and "close what this
            # sweep did not return" has no meaning. Defaulting the cutoff to
            # now() made that sentence close every open row instead, because
            # last_seen is always in the past. Refuse rather than guess.
            raise ValueError(
                "sweep-end on an authoritative source needs --run-start: "
                "the ISO timestamp captured before the sweep began. Without "
                "it every open %s record would be closed." % source)
        cutoff = run_start or ts
        args = [source, cutoff]
        sql = ("SELECT key, last_seen FROM postings "
               "WHERE source=? AND status='open' AND last_seen < ?")
        if employer:
            sql += " AND company_norm LIKE ?"
            args.append(f"%{norm(employer)}%")
        changed = []
        for row in self.db.execute(sql, args).fetchall():
            if authoritative:
                changed.append((row["key"], "closed"))
            else:
                age = _age_days(row["last_seen"])
                if age is not None and age > stale_after_days:
                    changed.append((row["key"], "stale"))
        for key, status in changed:
            self.db.execute(
                "UPDATE postings SET status=?, status_at=? WHERE key=?",
                (status, ts, key))
            self._log(key, ts, source, status, "")
        self.db.commit()
        return changed

    # -- selection --------------------------------------------------------
    def reclassify(self):
        """Recompute role_class/sector over the whole corpus.

        The patterns are heuristics and will be edited. Nothing depends on an
        old classification, so re-deriving is always safe and always cheap.

        `tags` is untouched: it is the hand-applied column, and the usual
        reason a tag exists is that a derived one of these got it wrong.
        """
        n = 0
        for row in self.db.execute(
                "SELECT key, title, company, location, text, remote "
                "FROM postings").fetchall():
            d = derived(dict(row))
            self.db.execute(
                "UPDATE postings SET role_class=?, sector=?, work_mode=?, "
                "state=?, country=?, auth=? WHERE key=?",
                (role_class(row["title"], row["text"]),
                 sector_of(row["company"]), d["work_mode"], d["state"],
                 d["country"], d["auth"], row["key"]))
            n += 1
        self.db.commit()
        return n

    def select(self, keywords=(), exclude=(), since_days=None, status="open",
               employer=None, location=None, remote=None, roles=(), sectors=(),
               include_reposts=False, include_seen=False, profile=None,
               min_score=0.0, limit=25, work_modes=(), states=(),
               countries=(), auth_exclude=(), auth=(), tags=(),
               state_exclude=(), employer_exclude=(), exclude_titles=()):
        """Narrow the corpus to a reviewable shortlist. Returns (rows, funnel).

        Three passes, each cheaper than the one it feeds:

        1. SQL on structured columns — status, date, location, state, work
           mode, role class, sector, work-authorisation gates, hand-applied
           tags — plus the dispositions you have already settled
           (applied, tailored, dismissed). This is the cut that takes a corpus
           of thousands down to hundreds, and it costs one indexed query.
        2. Keyword include/exclude over title and body, for the terms you
           name on the day.
        3. TF-IDF cosine against the profile, which orders what is left.

        Nothing is written. There is no cached verdict and no "already
        judged" state: the same posting re-scores on every run, because the
        thing it is being scored against is the profile, and that changes.
        """
        where, args = ["1=1"], []
        if status:
            where.append("status=?")
            args.append(status)
        if not include_reposts:
            where.append("repost_of=''")
        if employer:
            where.append("company_norm LIKE ?")
            args.append(f"%{norm(employer)}%")
        if location:
            where.append("(lower(location) LIKE ? OR remote=1)"
                         if remote is not False else "lower(location) LIKE ?")
            args.append(f"%{location.casefold()}%")
        if remote is True:
            where.append("(remote=1 OR work_mode='remote')")
        elif remote is False:
            where.append("remote=0 AND work_mode<>'remote'")
        if work_modes:
            where.append("work_mode IN (%s)" % ",".join("?" * len(work_modes)))
            args += list(work_modes)
        if states:
            where.append("state IN (%s)" % ",".join("?" * len(states)))
            args += [x.upper() for x in states]
        if state_exclude:
            # '' survives this, and must: a remote posting and a non-US one
            # both carry state='', and "not in Texas" is true of both. Only
            # a row that actually resolved to an excluded state is dropped.
            where.append("state NOT IN (%s)"
                         % ",".join("?" * len(state_exclude)))
            args += [x.upper() for x in state_exclude]
        if countries:
            where.append("country IN (%s)" % ",".join("?" * len(countries)))
            args += [x.upper() for x in countries]
        for e in employer_exclude:
            # AND-ed, not OR-ed: every name on the blocklist has to miss.
            where.append("company_norm NOT LIKE ?")
            args.append(f"%{norm(e)}%")
        if auth:
            frag, a = _set_clause("auth", auth)
            where.append(frag)
            args += a
        if auth_exclude:
            # The §2c gates. A posting whose body we do not hold has auth=''
            # and is kept: "not stated in the text we have" is not the same
            # as "no requirement", and dropping it would silently hide every
            # record that arrived without a description.
            frag, a = _set_clause("auth", auth_exclude)
            where.append("NOT " + frag)
            args += a
        for t in tags:
            frag, a = _set_clause("tags", [t])
            where.append(frag)
            args += a
        if roles:
            where.append("role_class IN (%s)" % ",".join("?" * len(roles)))
            args += list(roles)
        if sectors:
            where.append("sector IN (%s)" % ",".join("?" * len(sectors)))
            args += list(sectors)
        if since_days is not None:
            cutoff = (_dt.datetime.now(_dt.timezone.utc)
                      - _dt.timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            where.append("(first_posted>=? OR (first_posted='' AND first_seen>=?))")
            args += [cutoff, cutoff]
        if not include_seen:
            # Settled business. Applied and tailored are yours already;
            # dismissed is you saying no. None of them want reviewing again.
            where.append("key NOT IN (SELECT key FROM seen WHERE disposition "
                         "IN ('dismissed','tailored','applied'))")

        total = self.db.execute("SELECT count(*) FROM postings").fetchone()[0]
        rows = self.db.execute(
            "SELECT * FROM postings WHERE " + " AND ".join(where), args).fetchall()

        kws = [k.casefold().strip() for k in keywords if k.strip()]
        negs = [k.casefold().strip() for k in exclude if k.strip()]
        # Title-only, because the body is where a word turns up innocently:
        # "lecturer" in a list of the group's outreach duties should not
        # disqualify a research post, but "Lecturer" in the title should.
        negt = [k.casefold().strip() for k in exclude_titles if k.strip()]
        kept = []
        for row in rows:
            title = (row["title"] or "").casefold()
            body = (row["text"] or "").casefold()
            if any(neg in title or neg in body for neg in negs):
                continue
            if any(nt in title for nt in negt):
                continue
            if kws and not any(k in title or k in body for k in kws):
                continue
            kept.append(row)

        query = profile_text(profile) if profile else " ".join(kws)
        scores = similarity(
            query,
            # The title counts three times: a word in the body may be
            # boilerplate, a word in the title is the job.
            [(r["key"], " ".join([r["title"] or ""] * 3) + " " + (r["text"] or ""))
             for r in kept]) if query else {}

        out = []
        for row in kept:
            score = scores.get(row["key"], 0.0)
            if score < min_score:
                continue
            rec = _row_to_rec(row, with_text=False)
            rec["score"] = score
            out.append(rec)
        out.sort(key=lambda r: (-r["score"], r.get("first_posted") or ""))
        funnel = {"corpus": total, "after_filters": len(rows),
                  "after_keywords": len(kept), "above_min_score": len(out),
                  "returned": min(limit, len(out))}
        return out[:limit], funnel

    # -- retention --------------------------------------------------------
    def purge(self, older_than_days=365, statuses=("closed",), dry_run=False):
        """Actually delete rows. Deliberately hard to reach.

        A purged job can be rediscovered and re-bought, and a dismissed one can
        resurface. Only worth doing on long-dead records.
        """
        cutoff = (_dt.datetime.now(_dt.timezone.utc)
                  - _dt.timedelta(days=older_than_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        q = ",".join("?" * len(statuses))
        keys = [r["key"] for r in self.db.execute(
            f"SELECT key FROM postings WHERE status IN ({q}) AND status_at < ? "
            f"AND key NOT IN (SELECT key FROM seen WHERE disposition IN "
            f"('tailored','applied'))", list(statuses) + [cutoff])]
        if not dry_run and keys:
            self.db.executemany("DELETE FROM postings WHERE key=?", [(k,) for k in keys])
            self.db.executemany("DELETE FROM seen WHERE key=?", [(k,) for k in keys])
            self.db.commit()
            self.db.execute("VACUUM")
        return len(keys)

    # -- budget -----------------------------------------------------------
    def set_limit(self, api, limit):
        self.db.execute(
            "INSERT INTO budget_limit (api, limit_requests) VALUES (?,?) "
            "ON CONFLICT(api) DO UPDATE SET limit_requests=excluded.limit_requests",
            (api, int(limit)))
        self.db.commit()

    def _limit(self, api, default=None):
        row = self.db.execute(
            "SELECT limit_requests FROM budget_limit WHERE api=?", (api,)).fetchone()
        return row["limit_requests"] if row else default

    def used(self, api):
        row = self.db.execute(
            "SELECT requests FROM budget WHERE api=? AND month=?",
            (api, month())).fetchone()
        return row["requests"] if row else 0

    def spend(self, api, requests_used, limit=None):
        """Record quota spend. Returns (used_this_month, limit, over)."""
        if limit is not None:
            self.set_limit(api, limit)
        self.db.execute(
            "INSERT INTO budget (api, month, requests) VALUES (?,?,?) "
            "ON CONFLICT(api, month) DO UPDATE SET requests=requests+excluded.requests",
            (api, month(), int(requests_used)))
        self.db.commit()
        used = self.used(api)
        lim = self._limit(api, limit)
        return used, lim, (lim is not None and used > lim)

    def remaining(self, api, limit=None):
        lim = self._limit(api, limit)
        if lim is None:
            return None
        return max(0, lim - self.used(api))

    # -- politeness -------------------------------------------------------
    def throttle(self, source, min_interval=15.0, max_per_hour=20, sleep=True,
                 cost=1):
        """Wait until the next call to `source` is allowed, then record it.

        Two limits, because they stop different things. `min_interval` stops a
        burst, which is what gets an IP blocked. `max_per_hour` stops a loop
        that is polite per call and still hammers the site over an afternoon.

        `cost` is how many HTTP requests the caller is about to make, which is
        not always one: a scraper asked for 500 results pages through them
        back to back with no gap of its own. Charging the real number keeps
        the hourly cap honest, and the gap scales with it so a five-page call
        waits as long as five single-page calls would have.

        Returns the seconds waited. Raises if the hourly cap is already spent,
        rather than sleeping for up to an hour.
        """
        import time as _time
        now_dt = _dt.datetime.now(_dt.timezone.utc)
        hour_ago = (now_dt - _dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent = self.db.execute(
            "SELECT count(*) FROM rate WHERE source=? AND ts>=?",
            (source, hour_ago)).fetchone()[0]
        cost = max(1, int(cost))
        if max_per_hour and recent + cost > max_per_hour:
            oldest = self.db.execute(
                "SELECT min(ts) FROM rate WHERE source=? AND ts>=?",
                (source, hour_ago)).fetchone()[0]
            free_at = (_dt.datetime.strptime(oldest, "%Y-%m-%dT%H:%M:%SZ")
                       + _dt.timedelta(hours=1)).strftime("%H:%M:%SZ")
            raise SystemExit(
                f"{source}: {recent} requests in the last hour and this call "
                f"needs {cost}; cap is {max_per_hour}. A slot frees at "
                f"{free_at}. The corpus already holds what was fetched — "
                f"query it instead of re-scraping.")
        waited = 0.0
        last = self.db.execute(
            "SELECT max(ts) FROM rate WHERE source=?", (source,)).fetchone()[0]
        if last and min_interval:
            age = (now_dt - _dt.datetime.strptime(
                last, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=_dt.timezone.utc)).total_seconds()
            waited = max(0.0, min_interval * cost - age)
            if waited and sleep:
                _time.sleep(waited)
        ts = now()
        self.db.executemany("INSERT INTO rate (source, ts) VALUES (?,?)",
                            [(source, ts)] * cost)
        # A day of timestamps is far more than either window needs.
        self.db.execute("DELETE FROM rate WHERE ts < ?",
                        ((now_dt - _dt.timedelta(days=1))
                         .strftime("%Y-%m-%dT%H:%M:%SZ"),))
        self.db.commit()
        return waited

    def rate_status(self, source):
        hour_ago = (_dt.datetime.now(_dt.timezone.utc)
                    - _dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"last_call": self.db.execute(
                    "SELECT max(ts) FROM rate WHERE source=?",
                    (source,)).fetchone()[0],
                "requests_last_hour": self.db.execute(
                    "SELECT count(*) FROM rate WHERE source=? AND ts>=?",
                    (source, hour_ago)).fetchone()[0]}

    # -- watchlist --------------------------------------------------------
    def watchlist_add(self, employer, board_url="", platform="", via=""):
        self.db.execute(
            "INSERT INTO watchlist (employer, board_url, platform, added_at, added_via)"
            " VALUES (?,?,?,?,?) ON CONFLICT(employer) DO UPDATE SET "
            "board_url=CASE WHEN excluded.board_url<>'' THEN excluded.board_url "
            "ELSE watchlist.board_url END",
            (norm(employer) or employer, board_url, platform, now(), via))
        self.db.commit()

    def watchlist(self):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM watchlist ORDER BY employer")]


def read_posting_dir(path):
    """A fetch_posting.py output directory, as a corpus record.

    `fetch_posting.py --out DIR` leaves `jd.meta.json` and `job-posting.txt`
    (a provenance header, a blank line, then the body). Rebuilding that into
    a record by hand in a playbook is the kind of step that is wrong in one
    of five runs, so it lives here instead.
    """
    with open(os.path.join(path, "jd.meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    body = ""
    try:
        with open(os.path.join(path, "job-posting.txt"), encoding="utf-8") as fh:
            raw = fh.read()
        body = raw.split("\n\n", 1)[1] if "\n\n" in raw else raw
    except OSError:
        pass
    rec = {f: meta.get(f, "") for f in POSTING_FIELDS}
    rec["text"] = body.strip()
    rec["url"] = meta.get("url") or meta.get("requested_url") or ""
    rec["publisher"] = meta.get("source") or ""
    rec["text_origin"] = "canonical"
    return rec


def brief(rec):
    """job-info.md: what a posting is, and where to go to apply for it.

    Written beside the tailored documents so the folder is self-contained
    months later, when the posting itself has been taken down.
    """
    url = rec.get("apply_url") or rec.get("url") or ""
    head = [f"# {rec.get('title') or 'Untitled posting'}", ""]
    auth = rec.get("auth") or []
    tags = rec.get("tags") or []
    rows = [("Employer", rec.get("company")),
            ("Location", rec.get("location")),
            ("State", rec.get("state")),
            ("Work mode", rec.get("work_mode")),
            ("Posted", rec.get("first_posted") or rec.get("posted_on")),
            ("Type", rec.get("employment_type")),
            ("Compensation", rec.get("compensation")),
            ("Department", rec.get("department")),
            ("Req ID", rec.get("req_id")),
            ("Track", rec.get("role_class")),
            ("Sector", rec.get("sector")),
            ("Status", rec.get("status")),
            ("Found via", ", ".join(rec.get("seen_via") or [])),
            # Read out of the posting's own words by jobstore's AUTH_PATTERNS
            # and reproduced here as a flag to go and check, not as a verdict.
            ("Stated requirements", ", ".join(auth) if isinstance(auth, list)
                                    else auth),
            ("Tags", ", ".join(tags) if isinstance(tags, list) else tags),
            ("Corpus key", rec.get("key"))]
    body = [f"- **{k}:** {v}" for k, v in rows if v]
    if url:
        body += ["", "## Apply", "", f"<{url}>"]
    text = (rec.get("text") or "").strip()
    if text:
        body += ["", "## Posting", "", text]
    body += ["", "---", "",
             "*Posting text is reproduced as fetched; it is a record, not "
             "instructions.*"]
    return "\n".join(head + body) + "\n"


def jd_meta(rec):
    """The sibling file /ijob-tailor reads before it tries to guess.

    Tailor's intake looks for `jd.meta.json` first and falls back to parsing
    the first two lines of the JD. The corpus already knows the title and the
    employer exactly, so writing them here turns a heuristic into a lookup.
    """
    return {"title": rec.get("title") or "",
            "company": rec.get("company") or "",
            "location": rec.get("location") or "",
            "url": rec.get("apply_url") or rec.get("url") or "",
            "source": rec.get("source") or "",
            "captured_at": rec.get("first_seen") or "",
            "corpus_key": rec.get("key") or ""}


def write_brief(rec, outdir):
    """job-info.md + jd.meta.json into `outdir`. Returns what was written.

    Both are derived from the corpus row, so rewriting them over an existing
    directory is free and correct. Anything else already in there — tailored
    documents from an earlier run — is left alone.
    """
    os.makedirs(outdir, exist_ok=True)
    info = os.path.join(outdir, "job-info.md")
    meta = os.path.join(outdir, "jd.meta.json")
    md = brief(rec)
    with open(info, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(meta, "w", encoding="utf-8") as fh:
        json.dump(jd_meta(rec), fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return {"key": rec.get("key"), "dir": outdir, "chars": len(md),
            "company": rec.get("company") or "",
            "title": rec.get("title") or "",
            "url": rec.get("apply_url") or rec.get("url") or "",
            "has_text": bool((rec.get("text") or "").strip())}


def batch_dirname(rec):
    """`{company-slug}_{role-slug}` — the layout /ijob-tailor §2a builds.

    40, not the slug default of 60, because fetch_posting.target_dir uses 40.
    A job briefed out of the corpus and the same job fetched from its URL have
    to land on the same name or `--on-exist skip` tailors it twice.
    """
    return slug(rec.get("company") or "unknown", 40) + "_" + \
        slug(rec.get("title") or "role", 40)


def brief_target(batch, rec):
    """Where this posting's folder goes under `batch`. Never another's.

    Two distinct reqs routinely share an employer and a title — the same lab
    posting "Postdoctoral Researcher" twice in different groups. They collide
    on `{company}_{title}`, and write_brief would put the second on top of the
    first while the run summary still counted both. Suffix on a collision the
    way fetch_posting does, and keep the directory when the key matches, so
    re-briefing the same posting still resumes in place.
    """
    base = os.path.join(batch, batch_dirname(rec))
    key = rec.get("key") or ""
    path, n = base, 2
    while True:
        meta = os.path.join(path, "jd.meta.json")
        if not os.path.exists(meta):
            return path
        try:
            with open(meta, encoding="utf-8") as fh:
                held = json.load(fh).get("corpus_key") or ""
        except (ValueError, OSError):
            held = ""
        if held == key:
            return path
        path = "%s-%d" % (base, n)
        n += 1


def _read_keys(spec):
    """`--keys` as a comma list, or '-' for stdin.

    Stdin accepts either bare keys, one per line, or the JSON lines that
    `select` prints — so `select ... | brief --keys - --batch DIR` is the
    whole shortlist-to-folders step, with no key-copying in between.
    """
    if spec != "-":
        return [k.strip() for k in spec.split(",") if k.strip()]
    keys = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                k = json.loads(line).get("key")
            except ValueError:
                continue
            if k:
                keys.append(k)
        else:
            keys.append(line)
    # De-duplicated, order preserved: the same posting can arrive twice from
    # two concatenated selects, and briefing it twice is harmless but noisy.
    return list(dict.fromkeys(keys))


def _row_to_rec(row, with_text=True):
    rec = dict(row)
    rec["seen_via"] = json.loads(rec.get("seen_via") or "[]")
    rec["remote"] = bool(rec.get("remote"))
    for col in ("auth", "tags"):
        rec[col] = [v for v in (rec.get(col) or "").split(",") if v]
    if not with_text:
        rec["chars"] = len(rec.pop("text", "") or "")
    return rec


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _csv(v):
    return tuple(x.strip() for x in (v or "").split(",") if x.strip())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=DEFAULT_ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="append JSON-line records from stdin")
    p.add_argument("--source", required=True)
    p.add_argument("--status", default="open")

    p = sub.add_parser("ingest", help="add a fetch_posting.py output directory")
    p.add_argument("--dir", required=True, action="append",
                   help="directory holding jd.meta.json + job-posting.txt")
    p.add_argument("--source", default="direct")

    p = sub.add_parser("known", help="which keys already have a body")
    p.add_argument("--key", action="append", default=[])

    p = sub.add_parser("get")
    p.add_argument("--key", required=True)
    p.add_argument("--text", action="store_true", help="print the body only")

    p = sub.add_parser("find", help="query the corpus without pulling bodies")
    p.add_argument("--employer")
    p.add_argument("--status")
    p.add_argument("--source")
    p.add_argument("--disposition", choices=DISPOSITIONS)
    p.add_argument("--role", default="", help="comma-separated role classes")
    p.add_argument("--sector", default="", help="comma-separated employer sectors")
    p.add_argument("--work-mode", default="", help="remote,hybrid,onsite")
    p.add_argument("--state", default="", help="comma-separated USPS codes")
    p.add_argument("--tag", action="append", default=[],
                   help="hand-applied tag; repeatable, AND-ed")
    p.add_argument("--since", type=int, metavar="DAYS")
    p.add_argument("--limit", type=int, default=200)

    p = sub.add_parser("mark")
    p.add_argument("--key", required=True)
    p.add_argument("--disposition", required=True, choices=DISPOSITIONS)

    p = sub.add_parser("sweep-end")
    p.add_argument("--source", required=True)
    p.add_argument("--employer")
    p.add_argument("--stale-after-days", type=int, default=30)
    p.add_argument("--run-start", help="ISO timestamp this run began")

    p = sub.add_parser("budget")
    p.add_argument("--api", required=True)
    p.add_argument("--spend", type=int, default=0)
    p.add_argument("--limit", type=int)

    p = sub.add_parser("watchlist")
    p.add_argument("--add")
    p.add_argument("--board", default="")
    p.add_argument("--platform", default="")

    p = sub.add_parser("select", help="filter the corpus, then rank by profile fit")
    p.add_argument("--kw", action="append", default=[],
                   help="keyword the posting must mention; repeatable, OR-ed")
    p.add_argument("--not", dest="neg", action="append", default=[],
                   help="hard exclusion term; repeatable")
    p.add_argument("--role", default="",
                   help="comma-separated: " + ",".join(
                       [n for n, _ in ROLE_PATTERNS] + ["other"]))
    p.add_argument("--sector", default="",
                   help="comma-separated: " + ",".join(
                       [n for n, _ in SECTOR_PATTERNS] + ["company"]))
    p.add_argument("--employer")
    p.add_argument("--location", help="substring match; remote jobs still pass")
    p.add_argument("--remote", dest="remote", action="store_true", default=None)
    p.add_argument("--onsite", dest="remote", action="store_false")
    p.add_argument("--work-mode", default="",
                   help="comma-separated: remote,hybrid,onsite (derived; "
                        "finer than --remote/--onsite)")
    p.add_argument("--state", default="",
                   help="comma-separated USPS codes, e.g. IL,CA")
    p.add_argument("--state-exclude", default="",
                   help="comma-separated USPS codes to drop, e.g. TX. Remote "
                        "and non-US postings (state='') are not dropped")
    p.add_argument("--employer-exclude", action="append", default=[],
                   help="employer never to show; repeatable, substring match")
    p.add_argument("--not-title", dest="neg_title", action="append", default=[],
                   help="exclusion term matched against the title only; "
                        "repeatable. --not matches the body as well")
    p.add_argument("--country", default="", help="comma-separated, e.g. US")
    p.add_argument("--auth-exclude", default="",
                   help="drop postings stating these: " + ",".join(AUTH_NAMES) +
                        ". Applied locally, never sent to any source.")
    p.add_argument("--auth", default="",
                   help="keep only postings stating one of these")
    p.add_argument("--tag", action="append", default=[],
                   help="hand-applied tag the posting must carry; repeatable")
    p.add_argument("--since", type=int, metavar="DAYS",
                   help="posted (or first seen) within N days")
    p.add_argument("--status", default="open")
    # Relative to the engine repo, not the caller's cwd. The old cwd-relative
    # default meant running from anywhere else silently fell back to keyword
    # ranking against a profile that was sitting right there.
    p.add_argument("--profile",
                   default=os.path.join(os.path.dirname(os.path.dirname(
                       os.path.abspath(__file__))), "inputs", "profile.json"),
                   help="ranked against this; '' falls back to the keywords")
    p.add_argument("--min-score", type=float, default=0.0)
    p.add_argument("--limit", type=int, default=25, help="how many to return")
    p.add_argument("--count", action="store_true",
                   help="print the funnel only, no records")
    p.add_argument("--include-seen", action="store_true",
                   help="do not hide applied/tailored/dismissed")
    p.add_argument("--include-reposts", action="store_true")

    p = sub.add_parser("tag", help="hand-apply labels to one posting")
    p.add_argument("--key", required=True)
    p.add_argument("--add", action="append", default=[])
    p.add_argument("--remove", action="append", default=[])
    p.add_argument("--clear", action="store_true", help="drop all tags first")

    p = sub.add_parser("brief",
                       help="write job-info.md + jd.meta.json for one "
                            "posting, or a batch of them")
    p.add_argument("--key", help="one corpus key")
    p.add_argument("--keys",
                   help="comma-separated corpus keys, or '-' to read them "
                        "from stdin (one per line, or the JSON lines that "
                        "`select` prints). Requires --batch")
    p.add_argument("--out", help="directory to write a single posting into")
    p.add_argument("--batch", metavar="DIR",
                   help="batch root; each posting gets "
                        "DIR/{company-slug}_{role-slug}/, the layout "
                        "/ijob-tailor expects")

    sub.add_parser("reclassify", help="recompute role_class/sector over the corpus")

    p = sub.add_parser("purge", help="delete long-dead rows entirely")
    p.add_argument("--older-than", type=int, default=365, metavar="DAYS")
    p.add_argument("--status", default="closed")
    p.add_argument("--yes", action="store_true", help="required to actually delete")

    sub.add_parser("stats")

    p = sub.add_parser("dump", help="write the corpus out as JSON lines")
    p.add_argument("--text", action="store_true", help="include posting bodies")

    a = ap.parse_args(argv)
    st = Store(a.root)

    if a.cmd == "add":
        recs = [json.loads(l) for l in sys.stdin if l.strip()]
        res = st.append(recs, a.source, a.status)
        total = st.db.execute("SELECT count(*) c FROM postings").fetchone()["c"]
        print(json.dumps({"added": res["added"], "updated": res["updated"],
                          "unchanged": res["unchanged"], "split": res["split"],
                          "total": total}))

    elif a.cmd == "ingest":
        recs = [read_posting_dir(d) for d in a.dir]
        res = st.append(recs, a.source)
        print(json.dumps({"ingested": len(recs), "added": res["added"],
                          "updated": res["updated"],
                          "unchanged": res["unchanged"],
                          "split": res["split"], "keys": res["keys"]}))

    elif a.cmd == "known":
        print(json.dumps(st.known_many(a.key)))

    elif a.cmd == "get":
        rec = st.get(a.key)
        if not rec:
            print(f"no record for {a.key}", file=sys.stderr)
            return 1
        print(rec.get("text", "") if a.text
              else json.dumps(rec, ensure_ascii=False, indent=1))

    elif a.cmd == "find":
        for rec in st.find(a.employer, a.status, a.source, a.since,
                           a.disposition, a.limit, with_text=False,
                           roles=_csv(a.role), sectors=_csv(a.sector),
                           work_modes=_csv(a.work_mode), states=_csv(a.state),
                           tags=a.tag):
            print(json.dumps(rec, ensure_ascii=False))

    elif a.cmd == "mark":
        try:
            st.mark(a.key, a.disposition)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"key": a.key, "disposition": a.disposition}))

    elif a.cmd == "sweep-end":
        try:
            changed = st.sweep_end(a.source, a.employer,
                                   a.stale_after_days, a.run_start)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"changed": len(changed),
                          "closed": sum(1 for _, s in changed if s == "closed"),
                          "stale": sum(1 for _, s in changed if s == "stale")}))

    elif a.cmd == "budget":
        if a.spend or a.limit is not None:
            used, lim, over = st.spend(a.api, a.spend, a.limit)
        else:
            used, lim = st.used(a.api), st._limit(a.api)
            over = lim is not None and used > lim
        print(json.dumps({"api": a.api, "month": month(), "used": used,
                          "limit": lim, "remaining": st.remaining(a.api),
                          "over": over}))

    elif a.cmd == "watchlist":
        if a.add:
            st.watchlist_add(a.add, a.board, a.platform, "manual")
        print(json.dumps(st.watchlist(), indent=1))

    elif a.cmd == "select":
        profile = a.profile if a.profile and os.path.exists(a.profile) else None
        rows, funnel = st.select(
            keywords=a.kw, exclude=a.neg, since_days=a.since, status=a.status,
            employer=a.employer, location=a.location, remote=a.remote,
            roles=_csv(a.role), sectors=_csv(a.sector),
            include_reposts=a.include_reposts, include_seen=a.include_seen,
            profile=profile, min_score=a.min_score, limit=a.limit,
            work_modes=_csv(a.work_mode), states=_csv(a.state),
            countries=_csv(a.country), auth_exclude=_csv(a.auth_exclude),
            auth=_csv(a.auth), tags=a.tag,
            state_exclude=_csv(a.state_exclude),
            employer_exclude=a.employer_exclude, exclude_titles=a.neg_title)
        funnel["ranked_against"] = profile or "keywords"
        # The funnel goes to stderr so the records can be piped on untouched.
        print(json.dumps(funnel), file=sys.stderr)
        if not a.count:
            for r in rows:
                print(json.dumps(r, ensure_ascii=False))

    elif a.cmd == "tag":
        print(json.dumps({"key": a.key,
                          "tags": st.tag(a.key, a.add, a.remove, a.clear)}))

    elif a.cmd == "brief":
        if not a.key and not a.keys:
            print("brief needs --key or --keys", file=sys.stderr)
            return 2
        if a.keys and not a.batch:
            print("--keys writes a directory per posting; "
                  "give it --batch DIR", file=sys.stderr)
            return 2

        if a.keys:
            keys = _read_keys(a.keys)
            if not keys:
                print("no keys given", file=sys.stderr)
                return 1
            wrote, missing, no_text = [], [], 0
            for k in keys:
                rec = st.get(k)
                if not rec:
                    missing.append(k)
                    continue
                out = write_brief(rec, brief_target(a.batch, rec))
                no_text += 0 if out["has_text"] else 1
                wrote.append(out)
                print(json.dumps(out, ensure_ascii=False))
            # Summary on stderr so stdout stays one JSON object per job.
            # `bodyless` is the number /ijob-tailor will have to re-fetch
            # or tailor blind, and it must not be silent.
            print(json.dumps({"batch": a.batch, "requested": len(keys),
                              "wrote": len(wrote), "missing": missing,
                              "bodyless": no_text}), file=sys.stderr)
            return 1 if missing and not wrote else 0

        rec = st.get(a.key)
        if not rec:
            print(f"no record for {a.key}", file=sys.stderr)
            return 1
        target = a.out or (brief_target(a.batch, rec) if a.batch else None)
        if target:
            print(json.dumps(write_brief(rec, target), ensure_ascii=False))
        else:
            sys.stdout.write(brief(rec))

    elif a.cmd == "reclassify":
        print(json.dumps({"reclassified": st.reclassify()}))

    elif a.cmd == "purge":
        n = st.purge(a.older_than, tuple(a.status.split(",")), not a.yes)
        print(json.dumps({"rows": n, "deleted": bool(a.yes),
                          "note": "pass --yes to actually delete" if not a.yes else ""}))

    elif a.cmd == "stats":
        q = lambda s: {r[0]: r[1] for r in st.db.execute(s)}  # noqa: E731
        print(json.dumps({
            "db": st.path,
            "size_bytes": os.path.getsize(st.path),
            "records": st.db.execute("SELECT count(*) FROM postings").fetchone()[0],
            "with_text": st.db.execute(
                "SELECT count(*) FROM postings WHERE length(text)>0").fetchone()[0],
            "by_source": q("SELECT source, count(*) FROM postings GROUP BY source"),
            "by_status": q("SELECT status, count(*) FROM postings GROUP BY status"),
            "by_role": q("SELECT role_class, count(*) FROM postings GROUP BY role_class"),
            "by_sector": q("SELECT sector, count(*) FROM postings GROUP BY sector"),
            "by_work_mode": q("SELECT work_mode, count(*) FROM postings "
                              "GROUP BY work_mode"),
            "by_state": q("SELECT state, count(*) FROM postings WHERE state<>'' "
                          "GROUP BY state ORDER BY 2 DESC LIMIT 15"),
            # Per-flag, not per-combination: a posting demanding citizenship
            # and a clearance counts once under each.
            "stated_requirements": {
                name: st.db.execute(
                    "SELECT count(*) FROM postings WHERE (','||auth||',') LIKE ?",
                    (f"%,{name},%",)).fetchone()[0] for name in AUTH_NAMES},
            "tagged": st.db.execute(
                "SELECT count(*) FROM postings WHERE tags<>''").fetchone()[0],
            "dispositions": q("SELECT disposition, count(*) FROM seen GROUP BY disposition"),
            "budget": q(f"SELECT api, requests FROM budget WHERE month='{month()}'"),
            "watchlist": st.db.execute("SELECT count(*) FROM watchlist").fetchone()[0],
            "history_events": st.db.execute("SELECT count(*) FROM history").fetchone()[0],
        }, indent=1))

    elif a.cmd == "dump":
        for row in st.db.execute("SELECT * FROM postings ORDER BY first_seen"):
            print(json.dumps(_row_to_rec(row, a.text), ensure_ascii=False))

    st.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
