---
name: ijob-profile
description: Build or update profile.json, the structured career-data file the resume engine reads when tailoring. Use when the user asks to build, refresh, regenerate, or correct their resume profile, after they finish a new project, paper, or role that should appear on future resumes, or when /ijob-tailor halts because the profile is missing or stale.
---

# /ijob-profile — build or update profile.json

`profile.json` is the tag-indexed view the tailoring engine reads. Depending on setup it is either the source of truth itself, or a **derived index** of a richer record kept elsewhere.

## 1. Resolve paths

**Engine root.** `install.sh` rewrites this to an absolute path at install time. If it still reads `__ENGINE_PATH__`, the skill was copied by hand — resolve it yourself, in this order: `$RESUME_TAILOR_HOME`, then **the directory this `SKILL.md` is being read from** (its repo root is two levels up, and that is always the right answer when you are reading the playbook out of a clone). Never guess a conventional path such as `$HOME/soft/resume-tailor-agent`: on the author's own machine that is the live repo, so a run meant for a test copy writes into the real corpus and the real profile. If neither resolves, stop and ask — do not proceed against a guessed root.

```bash
ENGINE="__ENGINE_PATH__"
```

**Profile destination.** Resolve in this order:

1. **`$ENGINE/inputs/paths.yaml`**, if it exists — a non-empty `profile:` key is the destination, and a non-empty `profile_config:` key is the record config. Use this when the profile belongs somewhere other than the engine repo: a private record, a synced folder, a second machine's clone.
2. **`$ENGINE/inputs/profile.json`** — the default. `inputs/` is gitignored, so the profile stays private.

`$RESUME_TAILOR_PROFILE`, if set, overrides both.

**Mode.** Look for `profile-config.md`: at the `profile_config:` path if `paths.yaml` names one, otherwise beside the resolved profile.

- Found → **derived mode**. `RECORD` is that file's directory, `CONFIG` is the file.
- Not found → **standalone mode**.

**Announce the resolved destination before doing any work**, so the user can redirect it before a file appears somewhere they did not expect:

```
Mode:    derived (or: standalone)
Config:  <path to profile-config.md, or "none — standalone mode">
Writing: <absolute path to profile.json>
```

## 2. Pick the mode

**Derived mode** — a `profile-config.md` was found. The user keeps a richer career record and `profile.json` is generated from it. **Read the config and follow it.** It names the record's files, its conventions, any schema extensions, and the tagging vocabulary, and overrides the defaults below wherever they disagree.

In this mode `profile.json` is generated, never hand-edited. Adding a fact means editing the record and regenerating; otherwise the two drift and the resume starts citing things the record does not contain.

If a user wants derived mode but has no config yet, point them at `$ENGINE/inputs/profile-config.example.md` — it is the template and specifies the four sections. It can sit beside the profile, or anywhere `paths.yaml` points.

**Standalone mode.** No config was found. Follow the appendix below. Parse one or more CVs or résumés from `$ENGINE/inputs/`, fetch GitHub repositories, ask where the sources are ambiguous, and write the profile. The schema reference is `$ENGINE/inputs/profile.example.json`.

The profile is written to the resolved `$PROFILE` path. The default path, `$ENGINE/inputs/profile.json`, is gitignored and does not travel with a clone.

**External path, warn before the first write.** If `$PROFILE` is anywhere else, ask the user to confirm that the destination is private before writing. Do not run `git remote -v` or print a remote URL. A remote can contain an embedded credential, and repository visibility cannot be inferred safely from the local checkout. This is a warning, not a guarantee. Ask once per profile path, not on every run.

Mention this once after writing:

> Your profile is at `<path>`. If this is the default `inputs/` path, it is gitignored and stays on this machine. To sync it across machines, put it in a private repository or synced directory and point `profile:` in `inputs/paths.yaml` to it. If you already keep CVs, résumés, and notes that you would rather not retype, add a `profile-config.md` describing that record and rerun. `/ijob-profile` will switch to derived mode and regenerate the profile from the record. Templates are available at `$ENGINE/inputs/paths.example.yaml` and `$ENGINE/inputs/profile-config.example.md`.

Say it once. Do not repeat it on later runs in the same session.

## 3. Cold start vs update

- **Cold start** — no `profile.json`. Build from scratch.
- **Update** — it exists. Regenerate, then diff against the old file and show the user what changed before writing. Never silent-delete.

## 4. Tagging quality

The engine's module prefilter is tag-overlap, so weak tags mean weak module selection. This is the single biggest lever on output quality. Tag every bullet, project, and publication along whatever axes the record uses (derived mode: `$CONFIG` defines them), and always include **transferable** tags alongside specialist ones.

Specialist terms rarely appear in job postings verbatim. A posting says "molecular simulation", "ML for science", or "distributed computing" where a record says `ReaxFF`, `MLIP`, or `Parsl`. Without the transferable tags, a relevant posting prefilters to nothing.

## 5. Honest depth

Where the record calibrates how deep a skill actually goes, carry that into a `depth` field (`expert` | `working` | `familiar`). The tailoring pass must not present a `familiar` skill as a headline strength. This is the no-fabrication rule applied at the skills line.

## 6. References

Collect referees into `profile.references[]`. Each entry:

```json
{ "name": "", "title": "", "department": "", "organization": "",
  "email": "", "phone": "", "relationship": "", "default": false }
```

Sources, in order: an existing References section in the CV or record; `inputs/notes.md`; then ask. In derived mode the record's own conventions win, including which referees are currently active — a referee commented out in the record is deliberately inactive, so leave it out and mention that you saw it.

**Ask which one is the default.** Exactly one entry gets `"default": true`. That is the single reference `/ijob-tailor` prints under its default `--ref 1`, so it is a real choice and the user has to make it. Ask once, listing the collected names, after you have the full list. Never guess by ordering.

Never invent a referee, a title, or an email address. A wrong address here reaches a real person. If the CV shows a name but no email, leave `email` empty and say so rather than reconstructing one from a pattern.

If the user has no references to give, write `"references": []` and move on. `/ijob-tailor --ref 0` and templates without a References section both work fine without it.

## 7. Write and report

Write `$PROFILE` — the exact path announced in §1. Print counts per section, then batch any judgment calls into one set of questions at the end, not one at a time during the build.

If the destination already existed, show the diff and confirm before writing (§3).

### 7a. Rebuild the scoring PDF

Immediately after the profile is written, every time:

```bash
python3 -I "$ENGINE/scripts/profile_pdf.py" --profile "$PROFILE" --out "$ENGINE/inputs/profile-score.pdf"
{"ok": true, "pdf": ".../inputs/profile-score.pdf", "pages": 4, "bytes": 40306}
```

About a second. It renders **the whole profile** — every bullet, skill
and publication, no selection and no page budget — to `inputs/profile-score.pdf`,
on a deliberately absurd 26-inch-wide page. That is not a typo: the scorer
reads any short line starting with a letter as a section heading, so on letter
paper every wrapped bullet left a tail behind that became a fake section — 11
real headings against 11 invented ones. At 26in nothing wraps. Nobody looks at
this file, so the page can be whatever shape parses correctly.

That file is not a resume and is never sent to anyone. `/ijob-scrape` §5b scores
postings against it, and the scorer refuses any input that is not `.pdf` or
`.docx`, so the profile has to exist in one of those formats for a posting to
be measured at all. Because it holds everything, the number it produces is an
upper bound on achievable fit: if the person's entire record cannot match a
posting, no tailored subset of it will either.

Rebuild it here and nowhere else. It is derived from `$PROFILE`, so a profile
written without this step leaves a stale PDF on disk, and a shortlist scored
against yesterday's profile is worse than one not scored at all.

Failure is not fatal to this command: if `tectonic` is missing the script says
so and exits 2. Report it, point at `/ijob-setup`, and finish writing the
profile — but say plainly that `/ijob-scrape` will fall back to TF-IDF ordering
with no fit floor until it is built.

## 8. Search preferences — what `/ijob-scrape` will look for

`profile.json` says what the user *has done*. This section captures what they
*want next*, and it lands in a **different file**:

```bash
PREFS="$ENGINE/inputs/search-prefs.json"
```

**Why a separate file, and it is not negotiable.** `jobstore.py` flattens every
string in `profile.json` into the TF-IDF query that ranks postings. An exclusion
stored there would become a *positive* ranking term — put `"TX"` in the profile
and Texas jobs sort higher, which is the exact opposite of what the user asked
for. The cover-letter generator reads the same file, so a line like "needs visa
sponsorship" would be one bad generation away from reaching an employer. Keep
interests and exclusions out of `profile.json`. Both files are gitignored.

Offer the escape hatch **first**, before any question:

> These set your *default* job search — you can override any of it per run, so
> `/ijob-scrape remote only, posted this week` works without touching the file.
> Want to set them now, or take sensible defaults from your profile and tweak
> later?

**If they take defaults**, derive and write without further questions: positions
and keywords from the profile's strongest tags and recent titles, `recency_days`
30, sectors from where they have actually worked, no exclusions, the metered
`own_*` APIs marked enabled (they stay inert without an API key) and both
JobSpy scrapers off.
Then print what you wrote (the §8c block) so the defaults are visible rather
than assumed. One question total.

### 8a. If they want to set them — one at a time, each with its default stated

A bare "next" or "skip" accepts the default and moves on.

**Q1 — Positions.** The job titles to search with. Seed from the profile, show
the list, invite edits. These are transmitted to job sources, so they must read
like titles an employer would post, not like a self-description.

**Q2 — Keywords.** Extra terms that do not belong in a title. Seed from the
profile's specialist tags, and say that they are used to *filter locally*, not
to search — so a niche term costs nothing and risks nothing.

**Q3 — Sectors and places.** Which of `national_lab`, `government`,
`comm_college`, `university`, `nonprofit`, `company`; which states or cities;
and the work-mode preference (`remote`, `hybrid`, `onsite`, or any mix). Then
say the thing that is actually useful here:

> Academia and state jobs mostly sit on systems with no public API — those come
> through Indeed and LinkedIn, which are less complete than a direct board.
> National labs and industry we can read in full.

**Q4 — Recency.** Default 30 days. Note that the metered sources know when a job
*closes* and the scrapers do not, so scraped results skew stale and a tighter
window helps there.

**Q5 — Exclusions.** The gate. Phrase every one of these as a *filter on
postings*, never as a question about the user:

> Anything to rule out by default? I'll go one at a time — say "skip" to any, or
> "none" to skip them all.

| Ask | Stored under `job_exclusions` | Applied as |
|---|---|---|
| "Hide postings that require US citizenship?" | `auth: ["citizen"]` | `--auth-exclude citizen` |
| "...that require citizenship or a green card?" | `auth: ["citizen_or_pr"]` | `--auth-exclude citizen_or_pr` |
| "...that say they won't sponsor a visa?" | `auth: ["no_visa_sponsor","no_f1opt"]` | `--auth-exclude no_visa_sponsor,no_f1opt` |
| "...that need an active security clearance?" | `auth: ["clearance","export_ctrl"]` | `--auth-exclude clearance,export_ctrl` |
| "Any states to rule out?" | `states: ["TX"]` | `--state-exclude TX` |
| "Any employers never to show?" | `employers: [...]` | one `--employer-exclude` each |
| "Any job titles to rule out?" | `titles: ["lecturer"]` | one `--not-title` each |

Then, once, after the block — not after each question:

> These live in `inputs/search-prefs.json`, which is gitignored and never read by
> the résumé or cover-letter generators. They're applied on your machine *after*
> results come back — they are never sent to Indeed, LinkedIn or any API as part
> of a search.

That sentence is true because `/ijob-scrape` §3 forbids putting these terms in a
query. Do not write it unless that rule is still in force.

**Never ask the user about their own citizenship, visa status, or need for
sponsorship.** The questions above are about postings. The difference matters:
one is a filter, the other is personal data this repo has no reason to hold.

### 8b. The two scrapers — ask separately, or not at all

Only raise these if the user asked about job *volume* or about sources. They
default to off and a silent default-off is a fine outcome.

Ask them as **two independent questions**; a yes to one is never a yes to the
other. State the terms-of-service position plainly and do not soften it:

> There are two unmetered sources I can use, both of which scrape job boards
> from your machine in ways **their terms of service don't permit**. They don't
> touch any account of yours, but a block would land on your IP. Indeed returns
> 100 postings per request; LinkedIn costs about fifty times the traffic per
> posting and is capped at 50 results a call. Want either turned on?

On yes, run the enable command **without `--yes`**, so the user reads the full
warning and answers the prompt themselves:

```bash
python3 -I "$ENGINE/scripts/search_jobspy.py" --root "$ENGINE/inputs/scrape" enable --site indeed
python3 -I "$ENGINE/scripts/search_jobspy.py" --root "$ENGINE/inputs/scrape" enable --site linkedin
```

Record the outcome in `sources`, but the marker file the script writes is what
actually governs — `search-prefs.json` only reflects it.

**This repository and its authors provide no warranty and take no
responsibility for how it is used or modified, including any breach of a third
party's terms of service.** Say it once if either source comes up; do not
paraphrase it into something more comfortable.

### 8c. Write it, then show it

Write strict JSON. `search-prefs.json` does not support comments.

```json
{
  "version": 2,
  "job_interests": {
    "positions": ["computational materials scientist", "ML research scientist"],
    "keywords": ["interatomic potentials", "DFT", "MLIP"],
    "sectors": ["national_lab", "company"],
    "locations": {"places": ["Illinois"], "work_mode": ["remote", "hybrid"]},
    "recency_days": 30,
    "derived_from_profile": true
  },
  "job_exclusions": {
    "auth": ["citizen", "citizen_or_pr"],
    "states": ["TX"],
    "employers": [],
    "titles": ["lecturer"],
    "keywords": []
  },
  "sources": {
    "own_jsearch": {"enabled": true, "monthly_budget": 200},
    "own_linkedin": {"enabled": true, "monthly_budget": 200},
    "own_indeed": {"enabled": true, "monthly_budget": 200},
    "jobspy_indeed": {"enabled": false},
    "jobspy_linkedin": {"enabled": false}
  },
  "shortlist": {"fit_floor": 35},
  "watchlist": []
}
```

`derived_from_profile` becomes `false` after the user edits the interests. The three `own_*` entries express intent but still require `OWN_API_KEY`. The `jobspy_*` values must mirror `search_jobspy.py --root "$ROOT" status`; marker files remain authoritative. `shortlist.fit_floor` is requirement coverage as a percentage. Omit it or set it to `null` for the default of 35, or set it to 0 to disable the floor.

`derived_from_profile` matters: when it is `true`, a later `/ijob-profile` run
may refresh positions and keywords from the updated profile. Once the user has
edited them by hand it flips to `false` and **nothing overwrites them again** —
re-derive only if they ask.

`watchlist` starts empty and is appended to by discovery, not typed by hand.

Then print the whole thing back in plain language — positions, keywords,
exclusions, which sources are on — because this is the file that decides what
`/ijob-scrape` spends quota on, and the user should see it once while it is
still easy to change.

---

# Appendix — standalone-mode playbook

Follow this only in standalone mode (§2). Derived mode follows the record's `profile-config.md` instead.

`$PROFILE` is the only career-data file read by tailoring. Everything the résumé can say must appear there. In standalone mode, this playbook builds it from CVs, résumés, GitHub data, and user input, then updates it on later runs.

**Pre-req:** `/ijob-setup` has run (`"$ENGINE/tool"` exists at repo root) — needed only to parse a CV. If no CV is being parsed, `tool` is not required.

---

## Modes

- **Cold start** — `$PROFILE` does not exist. Build from scratch.
- **Update** — `$PROFILE` exists. Additive merge; never silent-delete.

`$PROFILE` is whatever §1 resolved. The precedence is `$RESUME_TAILOR_PROFILE`, then a non-empty `profile:` value in `$ENGINE/inputs/paths.yaml`, then `$ENGINE/inputs/profile.json`. Decide with `test -f "$PROFILE"`. Never use `test -f profile.json`. That tests the working directory and the old pre-`inputs/` location, so it can report a cold start for a user who already has a profile and then overwrite it.

## Inputs

All inputs are optional. The default input directory is `$ENGINE/inputs/`, which is gitignored. Accept multiple CVs and résumés in PDF, DOCX, Markdown, or plain-text format. Read Markdown and plain text directly. Only PDF and DOCX files need `tool --md` conversion.

| File | Purpose |
|---|---|
| `$ENGINE/inputs/cv*` or `$ENGINE/inputs/resume*` ending `.pdf`, `.docx`, `.md` or `.txt` | One or more existing CVs or résumés to parse. |
| `$ENGINE/inputs/github_username.txt` | One line containing the username. |
| `$ENGINE/inputs/notes.md` | Freeform context missing from the other sources. |

Those globs match files directly in `inputs/`, never directories, and only the four extensions above — a `cv.tex`, `resume.json` or `cv-old.bak` is not a source. If one is there, mention it once and let the user say whether to read it. **`inputs/resume-examples/` and `inputs/cover-letter-examples/` are not sources**: they are style references, `/ijob-tailor` §4a forbids taking facts from them, and a glob that descends into them would turn an old résumé's wording into profile facts. Skip `*.extracted.md` too — those are leftovers from earlier versions of this step, not something the user wrote. A `cv.md` sitting beside a `cv.pdf` may be one of those leftovers; ask once which is current.

The user places source files here. None is mandatory, but at least one source is strongly recommended for a cold start. When multiple documents overlap, merge corroborating information and ask about genuine conflicts. Do not silently choose between conflicting dates, titles, or claims.

---

## Flow

### 1. Load existing or empty profile

- Cold start → start with empty schema (see `inputs/profile.example.json` for shape).
- Update → load `$PROFILE`. Keep every existing field unless explicit user instruction to remove. Already-decided per-repo include/exclude flags carry over so the agent doesn't re-ask.

### 2. Parse each CV or résumé

Process every source document separately. Convert each PDF or DOCX into a scratch directory **outside `inputs/`**, named after the whole source filename, extension included:

```
EXTRACT="${TMPDIR:-/tmp}/ijob-profile-extract-$(printf %s "$ENGINE" | cksum | cut -d' ' -f1)"
rm -rf "$EXTRACT" && mkdir -m 700 "$EXTRACT"     # once, at the start of the run
"$ENGINE/tool" "$ENGINE/inputs/cv-primary.pdf" --md "$EXTRACT/cv-primary.pdf.md"
```

- **Outside `inputs/`** because an extraction left there matches the `cv*` glob on the next run and is read as a source of its own. Delete or replace the PDF and its old extraction survives, quietly restoring facts the user removed.
- **Wiped and recreated, not `mkdir -p`.** That clears anything a previous run left, and it is the only way the `700` takes effect — `mkdir -p -m` leaves an existing directory's permissions as they were. It also makes `--md`'s refusal to overwrite moot, since nothing is there to collide with.
- **Named per clone, not `mktemp -d`.** A design choice, not a limitation: a random path would work if it were written down and carried from command to command, but every shell call starts fresh, and a deterministic name is one any later command can rebuild with no extra state to keep. The checksum of `$ENGINE` gives every clone its own folder, so a test clone running beside the real one cannot wipe its files. Two runs on the *same* clone would already be fighting over one `profile.json`; do not start a second.
- **Extension in the name** because `cv.pdf` and `cv.docx` would both become `cv.md`, and the second conversion would quietly land in `cv-2.md`.
- **Removed at the end** — see §8. This is the user's whole career in plain text; it should not outlive the run.

Read every source and extract:
- `identity` (name, location, contact links).
- `summary_seeds` — raw factual statements, NOT a pre-written summary.
- `skills` (languages, frameworks, tools, domains).
- `experience` (company, title, dates, bullets — keep bullets verbatim, mark any with concrete numbers in `metric`).
- `projects`, `education`, `certifications`.

If CV is genuinely ambiguous about something (e.g., dates say "Recent"), ask — don't guess.

### 3. GitHub fetch if username present

```
curl -fsSL "https://api.github.com/users/<USERNAME>/repos?per_page=100&sort=updated&type=owner"
```

Unauthenticated. 60 req/hr is plenty — one user-repos call is one request. If rate-limited, halt with "wait until <X-RateLimit-Reset>" + re-run hint.

Skip forks (`fork: true`) by default. For each remaining repo:

- Read `name`, `description`, `language`, `stargazers_count`, `html_url`, `topics`.
- If update mode and this repo already has `enrichment.github.repos[name].included` set → skip the question, honor the prior decision.
- Else ask: `Include "<name>" — <description>? [Y/n] (glob: "skip-pattern" to blanket-skip)`. Default Y. A glob answer (e.g., `experiments-*`) excludes all matching repos at once and is remembered.
- Included + substantial repos (has README, > N lines, or user-flagged) → add to `projects[]`. All repos (included or not) recorded in `enrichment.github.repos[]` with their `included` flag.

### 4. Read notes.md

Read `$ENGINE/inputs/notes.md` if present. Treat the user's notes as authoritative when an extracted document omitted or misparsed a fact. If the notes conflict with a clear source document, ask rather than guessing.

### 4b. References

Parse a References section out of the CV if one exists. Record name, title, department, organization, and email into `references[]`. Then ask which is the default (main §6, References — not the appendix's §6, which derives tags). Do not fabricate missing emails.

### 5. Ask clarifying questions — only on genuine gaps

NO interrogation. Skip every question you can answer from inputs. Ask only when something is missing AND the résumé needs it. Examples worth asking:

- Missing contact field the CV shows in a non-text logo (`linkedin.com/in/...`).
- Date ambiguity ("Recent", "current" without context).
- Target domains, meaning which tags should weigh higher in `/ijob-tailor` relevance selection (`data`, `backend`, `frontend`, `devops`, `security`, `ml`, and similar tags).

### 6. Derive tags

Every `skills[].*`, `experience[].bullets[]`, `projects[].bullets[]` gets a `tags: []` array. Tags = lowercase keywords lifted from the text (`python`, `etl`, `kafka`, `react`, `terraform`). Hand-editable later. These drive relevance selection in `/ijob-tailor`.

### 7. Diff + confirm

- **Update mode:** print a unified diff of `$PROFILE` (old vs new). Ask `apply? [Y/n]`. On Y, write file. On n, abort — no partial writes.
- **Cold start:** print compact summary of proposed profile (counts per section + identity). Ask `write profile.json? [Y/n]`.

### 8. Write

Pretty-printed JSON, 2-space indent, sorted top-level keys per schema order (see `inputs/profile.example.json`, which now includes `references[]`).

Then `rm -rf "$EXTRACT"` (rebuild it exactly as §2 does) — the extractions are not needed once the profile is written. Do it on a halt too.

Set `meta.last_updated` to current ISO8601. Set `meta.source` to `"cv"`, `"github"`, `"manual"`, or comma-joined for hybrids.

---

## Non-negotiables

- **No fabrication.** If CV unclear → ask, don't guess. If GitHub repo description is empty, leave it empty, don't invent.
- **No silent delete.** Update mode keeps anything not explicitly removed. Even unused tags stay.
- **Protect personal data.** The default `$ENGINE/inputs/profile.json` path is gitignored. For an external `$PROFILE`, give the privacy warning in main §2 (*Pick the mode*) before the first write. Never log the profile or send it anywhere except as context for the active LLM session.

## Failure modes

- **Tool cannot parse a document** → ask the user to save a cleaned Markdown or plain-text copy under `$ENGINE/inputs/`, then rerun. Continue with other readable source documents if they are sufficient.
- **GitHub rate-limited** → halt, print the reset time, and suggest rerunning later.
- **Network unavailable** → a cold start can continue with local CVs, résumés, and notes. Record the available sources in `meta.source`.
- **No inputs at all** → halt with: "Add one or more CVs or résumés under `$ENGINE/inputs/`, add `$ENGINE/inputs/notes.md`, and/or provide a GitHub username, then rerun."

## Schema reference

See `inputs/profile.example.json` for the exact shape.
