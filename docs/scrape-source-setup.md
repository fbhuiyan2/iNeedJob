# `/ijob-scrape` source setup

> **This page is for you, not your agent.** It involves visiting websites and
> creating accounts, which only a person can do. If you are setting things up
> generally, start with the [README](../README.md) instead.

**The short version:** create one free [OpenWeb Ninja](https://rapidapi.com/)
account, subscribe to the free tier of each of the three APIs named below
(separately — one key, three quotas), and paste the key into
`inputs/secrets.env`. That is enough to run `/ijob-scrape`.

How to get credentials for each discovery source. Every source here is free and
requires no credit card — that is the standing constraint, and anything that fails it
is listed at the bottom with the reason.

Credentials live in **`inputs/secrets.env`**, which is gitignored (`inputs/*`) and
should be `chmod 600`. Nothing here is ever committed, logged outside the repo, or
sent anywhere except the source it authenticates to.

```bash
# inputs/secrets.env
OWN_API_KEY=ak_...
```

---

## No setup needed

| Source | Notes |
|---|---|
| **Direct employer boards** | Public JSON APIs. No key, no account, unlimited. Already working via `scripts/fetch_posting.py` |
| **LinkedIn via JobSpy** | No account, no key, but **off by default and opt-in per site** — see the JobSpy section below. Not the same thing as a LinkedIn API |

---

## Not built yet

**USAJOBS** and a standalone **LinkedIn guest** client are designed but not
implemented — `scripts/` has USAJOBS only as a tier constant and a URL pattern.
There is nothing to configure, and `USAJOBS_API_KEY` / `USAJOBS_EMAIL` do
nothing if you set them. The section below is kept as the spec for whoever
builds it; skip it as a user.

## USAJOBS — federal jobs (not implemented)

Free, no card, no advertised rate limit. Covers **federal civil service only** —
NIST, NETL, NASA and the agencies. It does *not* cover the contractor-operated
national labs (Argonne, Sandia, LANL, ORNL, PNNL), whose staff are employed by
universities and contractors rather than the government. Enable it when the
"Government (federal)" category is selected; it will return nothing useful otherwise.

**Getting a key:**

1. Go to <https://developer.usajobs.gov/apirequest/>
2. Fill in the full form. For a personal job search:
   - **Company or Agency:** `Personal`
   - **How will your agency/company use the jobs obtained from this site:**
     `For personal job search purposes`
3. They email you a confirmation link. Confirm the address.
4. A second email arrives with the API key.

**Using it** — two headers, both required:

```
User-Agent: <the email you registered with>
Authorization-Key: <the key>
```

```bash
curl -s -H "User-Agent: $USAJOBS_EMAIL" -H "Authorization-Key: $USAJOBS_API_KEY" \
  "https://data.usajobs.gov/api/search?Keyword=materials+scientist&LocationName=Illinois"
```

Note: the API does **not** validate that the `User-Agent` matches the registered
address — measured; any non-empty string is accepted. So `USAJOBS_EMAIL` is optional
in practice and the client falls back to a generic agent string when it is blank.
Setting it to the real address is still preferable: it is what their terms ask for,
and it is how they would contact you before imposing a quota.

**Gotcha:** `Organization=` expects an agency *code*, not a name. Passing
`Organization=NIST` silently returns zero. Use `Keyword=` for name searches.

---

## OpenWeb Ninja — the three metered discovery APIs

Free, email signup, **no credit card**. This is what reaches the employers whose own
job boards block us — UIUC, UIC, College of DuPage, Illinois State, Northwestern,
PNNL, Sandia, Oak Ridge, INL. Measured: `scrape-probes/openweb-ninja.md`.

**Getting the key, step by step:**

1. Go to <https://www.openwebninja.com/> and create an account (email + password).
   No card is asked for at any point; if one is, you are on the wrong plan.
2. **Subscribe to each of these three APIs separately, on the Free plan.** Search
   the catalogue for each name and press Subscribe on the $0/mo tier:
   - **JSearch**
   - **Real-Time LinkedIn Data**
   - **Real-Time Indeed Data**
3. Copy the key once, from the portal's API-key page, into `OWN_API_KEY` in
   `inputs/secrets.env` (`chmod 600`, gitignored).

**One key, three separate quotas.** This is the part that catches people out: the
*key* is per account and the same string works for all three, but the *free tier is
per API* and does not exist until you subscribe to that API. A key that works
perfectly against JSearch returns `403 "You are not subscribed to this API"` from
Real-Time Indeed Data until you press Subscribe there too — and a 403 is not billed,
so the symptom is a source that silently never returns anything rather than an error
you would notice.

Each subscription carries **its own 200 requests/month** (and 1,000/hour). They are
not pooled and not redundant:

| API | Path in this repo | Its own free tier | What it is for |
|---|---|---|---|
| **JSearch** | `/jsearch/search-v2` | 200 req/mo | Named-employer enumeration. The only one that reaches the national labs |
| **Real-Time LinkedIn Data** | `/realtime-linkedin-data/search` | 200 req/mo | Broad discovery. Loose matching, reliable dates |
| **Real-Time Indeed Data** | `/realtime-indeed-data/search` | 200 req/mo | Topical search with a real `location` filter. ATS apply links and an expiry flag. Weak on national labs |

Together that is 600 requests a month, roughly 200 three-page queries.
Check what you have actually subscribed to with `search_own.py quota`, which reports
the local ledger per API — and remember that the ledger is this repo's own count, not
the vendor's, because no response carries a remaining-quota header.
JSearch is precise on a named employer; the LinkedIn API matches loosely and is the
one that finds employers you did not know to name, and it carries reliable posting
dates. Endpoint: `https://api.openwebninja.com/realtime-linkedin-data/search`,
same `X-API-Key` header, results in `data` as a plain list rather than under
`data.jobs`.

```bash
curl -sS -G 'https://api.openwebninja.com/jsearch/search-v2' \
  --data-urlencode 'query=Sandia National Laboratories' \
  --data-urlencode 'num_pages=3' \
  -H "X-API-Key: $OWN_API_KEY"
```

**Quota gotcha:** the quota counts *requests*, not calls. `num_pages=3` is one call
billed as three requests, returning ~30 jobs. So 200/month buys roughly **2,000
postings**. There is no remaining-quota header — the only accounting signal is
`x-rapidapi-billing: Queries=N; Requests=M` on each response, so the spend ledger
has to be kept locally.

---

## Indeed and LinkedIn via JobSpy — unmetered, unsanctioned, off by default

**Opt-in only, and per site. Read this before enabling either.** Every other source
in this file is a public API, a first-party key, or a vendor that absorbs the
scraping on its own servers. This one scrapes **from your machine, on your IP**.

- **Neither site's terms of service permit scraping.** Enabling it is your call.
- **A block lands on you**, not on a vendor.
- **It can fail silently.** It reads page layout; a redesign returns zero results
  rather than an error until JobSpy ships a fix. Historically days — the project is
  actively maintained (MIT, ~4.5k stars, releases every week or two) — but you pick
  the fix up with `check --refresh`.
- **Indeed and LinkedIn only.** Glassdoor, ZipRecruiter and the rest are not
  reachable from here; the runner accepts those two names and nothing else.

**LinkedIn here is the logged-out endpoint.** JobSpy clears cookies and sends no
credentials, so your LinkedIn account is not involved and a block would be at the IP
level, not an account action. That is a smaller risk than account scraping, not no
risk — and LinkedIn's scraper has a branch for "unexpected page with no jobs
(blocked?)", which tells you what its authors expect to happen.

**The two sites are not equivalent**, measured in JobSpy 1.4.1:

| | Indeed | LinkedIn |
|---|---|---|
| Postings per search request | 100 | 10 |
| Description | in the search response | **a second request per posting** |
| JobSpy's own delay | none | 3–7 s between search pages, none between descriptions |
| Requests for 50 postings with text | 1 | 55 |
| Our limit | 20 s/request, 15/hour ≈ **1,500 postings/hour** | 2 s/request, 200/hour ≈ **180 postings/hour** |
| Results per call | uncapped | **capped at 50** |

LinkedIn therefore costs roughly fifty times the traffic per posting. The per-call
cap exists because JobSpy fires those description requests back to back with no sleep
of its own — a burst this repo cannot slow from outside, so the only control is to
keep each call short and let the throttle space the calls.

**Requirements:** Python and [`uv`](https://docs.astral.sh/uv/). Nothing is installed
into this repo or your system Python — `uv run --with` resolves JobSpy into its own
cache.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # if you do not have uv

python3 -I scripts/search_jobspy.py check                  # uv present? JobSpy resolves?
python3 -I scripts/search_jobspy.py enable --site indeed   # prints the warning, asks
python3 -I scripts/search_jobspy.py enable --site linkedin # a separate decision

python3 -I scripts/search_jobspy.py search --site indeed \
         --query "computational scientist" --location Illinois --hours-old 168
python3 -I scripts/search_jobspy.py search --site linkedin \
         --query "computational materials scientist" --location Illinois --results 25

python3 -I scripts/search_jobspy.py status                 # both sites, limits, recent rate
python3 -I scripts/search_jobspy.py disable --site linkedin
```

Rate limits live in the corpus database rather than the process, so they hold across
separate runs and across a crash. **The unit is the HTTP request, not the query** —
`--results 500` on Indeed is five requests and is charged as five; `--results 25` on
LinkedIn is three search pages plus 25 description fetches and is charged as 28. The
required gap scales with the charge, so a call that makes 28 requests waits as long
as 28 single-request calls would have.

Two LinkedIn quirks worth knowing: `--remote` is ignored by its endpoint (filter
afterwards with `jobstore.py select --work-mode remote`), and a few description
fetches per run come back empty because the job page redirects to a login wall —
the run reports "N results, M with text" so the gap is visible.

Pass `--hours-old 168` on repeat sweeps; everything found is stored locally and never
re-fetched, so there is no reason to scrape broadly twice.

### Disclaimer

This software is provided "as is", without warranty of any kind, under the terms of
the [LICENSE](../LICENSE) file in this repository. Neither the repository nor its
authors or contributors are responsible for how it is used or modified, for any
breach of a third party's terms of service arising from that use, or for any
consequence of it. Enabling an unsanctioned source is the user's decision, taken
after reading the warning the `enable` command prints, and the responsibility for it
is theirs alone. Nothing here is legal advice.

---

## Indeed — via MCP (blocked, 2026-10-23)

**Do not spend time on this.** The sign-in works and the result is still unusable.
Use **Real-Time Indeed Data** (above) instead — same inventory, reached through the
vendor, works from a terminal.

Free, needs an Indeed account, no card. Server: `https://mcp.indeed.com/claude/mcp`.
A stdlib client completed the whole OAuth 2.1 flow — RFC 7591 dynamic registration,
PKCE S256, loopback callback, refresh token on disk. `secure.indeed.com` issued a
real token:

```
aud:   ["https://default.indeed.com", "https://mcp.indeed.com/claude/mcp"]
scope: "offline_access job_seeker.jobs.search"
```

Every MCP call then returns:

```
403 {"error": "invalid_client", "error_description": "Client not allowed"}
```

The token is valid and correctly bound to the resource. The **client** is refused.
`/claude/mcp` is provisioned for one allowlisted client; `/mcp`, `/v1/mcp` and `/sse`
are 404, so there is no general endpoint for a self-registered one. Nothing on our
side fixes this.

Two smaller findings from the same session, both already fixed in the script and both
worth knowing if you build against this API:

- **Registration needs a JSON body.** The token endpoint takes form encoding
  (RFC 6749), registration takes JSON (RFC 7591). Indeed enforces it with a bare
  `415` and an HTML error page.
- **The resource server advertises scopes the authorization server will not
  register.** `.well-known/oauth-protected-resource` lists four;
  `job_seeker.profile.read` and `job_seeker.company.details.read` fail at `/register`
  with *"Requested scopes are invalid or not supported"*, and because one bad scope
  fails the whole request, asking for all four fails everything. Only
  `job_seeker.jobs.search` and `offline_access` register.

**The Claude Code connector fails identically** — tested. `claude mcp add` succeeds,
the health check reports "Needs authentication", `/mcp` completes the sign-in, and
the server then rejects the credentials on reconnect:

```
Got new credentials, but indeed rejected them on reconnect.
```

Two independent clients, both correctly authenticated, both refused. The common
factor is *dynamic* registration — `/claude/mcp` expects a pre-issued, allowlisted
`client_id`. The client code and the stored token were deleted; this note is what
remains.

---

## Rejected, and why

| Source | Reason |
|---|---|
| **Adzuna** | Signup gives a "Pending Activation" key good for **25 test calls**. Real use is 5,000/mo for £8/mo and needs a card. Fails the no-card constraint |
| **RapidAPI / JSearch** | Free tier is 200 req/mo, but RapidAPI's own storefront is returning Cloudflare 503s; the direct vendor (OpenWeb Ninja) is 200/mo free — usable but thin, and paid tiers need a card |
| **SerpApi** | 250 searches/mo free, no card, and it does work — but it reads the same Google for Jobs index as JSearch from a quota shared across ~40 engines, where JSearch's 200 is dedicated. Keep as an alternate, not a default |
| **Careerjet** | Requires a Publisher account and the end user's IP and User-Agent on every call. Designed for running a job board, not a personal search |
| **Composio** | Its Workday/Greenhouse/Lever toolkits are employer-side and need each employer's ATS credentials. Its LinkedIn toolkit has no job search at all |
| **Keyless remote feeds** | RemoteOK, Remotive, Jobicy, Himalayas, Arbeitnow, WeWorkRemotely, HN Who-Is-Hiring: 0 of 33 targets across ~1,200 postings. All remote-tech-startup skewed |
| **The Muse** | Keyless and carries 230 Sandia postings, but its curated 968-partner list contains no other target. Worth a single-employer special case at most |
