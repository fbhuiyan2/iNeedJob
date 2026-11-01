# How to set up resume-tailor-agent — agent reference

> **This document is written for an agent, not for a person.**
>
> If you are a human setting this up, you do not need any of it. Start a session
> in any harness and say *"clone this repo and set it up for me"* — that is the
> entire user-facing instruction, and the [README](../README.md) shows what happens
> next. Everything below is the detail an agent needs when the simple path is
> not enough.

[`AGENTS.md`](../AGENTS.md) is the entry point and covers the ordinary case in four
steps. **Read this file instead when one of these applies:**

| Situation | Section |
|---|---|
| The harness is not in the installer's table, or shims must be written by hand | [Step 4](#step-4--what-the-shims-are-if-you-want-to-write-them-by-hand) |
| The profile belongs outside the repo — a private repo, a synced folder | [Step 5](#step-5--environment-variables-all-optional), [Step 6](#step-6--build-your-profile) |
| Setting up a machine that already has a profile somewhere | [Setting up a second machine](#setting-up-a-second-machine) |
| The user wants job discovery and needs credentials | [Step 7](#step-7--job-sources-only-if-you-want-the-job-finding-half) |
| Something is broken | [Troubleshooting](#troubleshooting) |

Makes all five commands — `/ijob-tailor`, `/ijob-profile`, `/ijob-setup`,
`/ijob-scrape`, `/ijob-shortlist` — work **from any directory**, in any harness,
on any machine. The playbooks stay in this repo, a thin skill layer in the home
directory points at them, and the user's personal profile lives somewhere
private.

---

## The shape of it

Five moving parts, deliberately kept separate:

| Part | Lives in | Why there |
|---|---|---|
| **Engine** — playbooks, templates, references, binaries | this repo | Public and shareable. Personal data may exist only under gitignored `inputs/`; it must never be tracked or committed. |
| **Slash commands** — all five | this repo's `skills/`, installed to `~/.claude/skills/` and every other harness directory found | Generic logic, no personal data. Read by Claude Code AND OpenCode, from any directory. |
| **Profile** — your career record + generated `profile.json` | `inputs/profile.json`, gitignored. Optionally a **private repo of your own**, pointed at by `profile:` in `inputs/paths.yaml` | Data only, no logic. Never in the public engine repo. |
| **Corpus** — every posting `/ijob-scrape` has ever seen | `inputs/scrape/jobs.db`, gitignored | Months of quota-bought text. Local, private, never committed. |
| **Outputs** — per-job resumes, letters, scores | next to the JD, else `./resume-agent-output_{company}-{role}/` | Lands where you are working. Never inside the engine repo. |

Why the split: `profile.json` holds your email, phone, and full career history. This repo is public. Committing the profile here publishes it.

---

## Why skills, not slash commands

Discovery paths differ between the two tools, and only one artifact type is shared:

| Location | Claude Code | OpenCode |
|---|---|---|
| `~/.claude/skills/<name>/SKILL.md` | ✅ any dir, invocable as `/name` | ✅ any dir (reads `~/.claude/skills` natively) |
| `~/.claude/commands/*.md` | ✅ any dir | ❌ not read |
| `~/.config/opencode/command/*.md` | ❌ not read | ✅ any dir |

So the real logic goes in a **skill** — written once, both tools see it. OpenCode surfaces skills through a `skill` tool that the agent picks by description, so if you want a literal `/ijob-tailor` keystroke there too, add the three-line command shims in step 4.

---

## Step 1 — clone the engine

```sh
git clone https://github.com/fbhuiyan2/resume-tailor-agent ~/soft/resume-tailor-agent
```

Any path works — `install.sh` bakes the absolute path into the skills. Re-run the installer if you later move the repo.

## Step 2 — fetch the binaries

Per machine, since both are gitignored. On a fresh clone, read and follow [`skills/ijob-setup/SKILL.md`](../skills/ijob-setup/SKILL.md) directly. The `/ijob-setup` alias becomes available after Step 3 and a harness restart. The manual example below is for Linux x86_64 only:

```sh
cd ~/soft/resume-tailor-agent
curl -fL -o tool "https://github.com/NoahMustafa/open-ATS/releases/download/v0.2.0/tool-linux-x86_64"
chmod +x tool
curl -fL -o tectonic.tar.gz "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic@0.17.0/tectonic-0.17.0-x86_64-unknown-linux-musl.tar.gz"
tar -xzf tectonic.tar.gz && chmod +x tectonic && rm tectonic.tar.gz
./tool --version && ./tectonic --version
```

Check the releases pages for newer tags. Tectonic publishes sub-crate releases on the same page — only tags starting `tectonic@` ship the compiler.

First LaTeX compile downloads a package cache (~50 MB, one time). A slow first run is normal.

## Step 3 — install the slash commands

```sh
bash ~/soft/resume-tailor-agent/skills/install.sh
```

That copies all five skills into `~/.claude/skills/` — and into every other harness directory it finds under `$HOME` — and writes the OpenCode command shims. Idempotent — re-run after a `git pull` to pick up playbook changes.

What it installs:

```
~/.claude/skills/
├── ijob-tailor/SKILL.md
├── ijob-profile/SKILL.md
├── ijob-scrape/SKILL.md
├── ijob-shortlist/SKILL.md
└── ijob-setup/SKILL.md

~/.config/opencode/command/
├── ijob-tailor.md
├── ijob-profile.md
├── ijob-scrape.md
├── ijob-shortlist.md
└── ijob-setup.md
```

Each skill is self-contained: it resolves the engine path and the profile in its own §1, then carries the full procedure inline. No indirection, nothing to keep in sync.

Frontmatter must satisfy both tools: `name` (lowercase, hyphenated, **matching the directory name**) and `description` are required; unknown fields are ignored. Write the description specifically — it is how OpenCode decides whether to invoke the skill.

## Step 4 — what the shims are, if you want to write them by hand

Only needed for literal `/ijob-tailor` keystrokes in OpenCode; `install.sh` already writes them. Both `command/` and `commands/` are accepted; singular shown.

`~/.config/opencode/command/ijob-tailor.md`:

```markdown
---
description: Tailor a resume + cover letter to a job description (resume-tailor-agent)
---
Invoke the `ijob-tailor` skill and follow it exactly. Arguments: $ARGUMENTS
```

`~/.config/opencode/command/ijob-profile.md`:

```markdown
---
description: Build or update profile.json
---
Invoke the `ijob-profile` skill and follow it exactly. Arguments: $ARGUMENTS
```

`~/.config/opencode/command/ijob-setup.md`:

```markdown
---
description: Bootstrap the resume-tailor-agent binaries (open-ATS scorer + Tectonic)
---
Invoke the `ijob-setup` skill and follow it exactly. Arguments: $ARGUMENTS
```

Without these, OpenCode still works — you just say "tailor my resume to this JD" and the agent invokes the skill by description.

## Step 5 — environment variables (all optional)

Nothing is required. The skills resolve everything themselves:

- **Engine path** is baked in by `install.sh`. Re-run it if you move or re-clone the repo.
- **Profile** defaults to `inputs/profile.json`, which is gitignored. To keep it elsewhere — a private repo, a synced folder — set `profile:` in `inputs/paths.yaml`.
- **Output** is decided per run: next to the JD file if you gave a path, otherwise `./resume-agent-output_{company}-{role}/` in the current directory. Never inside the engine repo.

Override any of them only if you want to:

```sh
export RESUME_TAILOR_HOME="$HOME/soft/resume-tailor-agent"   # engine repo
export RESUME_TAILOR_PROFILE="/path/to/profile.json"       # skip discovery
export RESUME_TAILOR_OUT="$HOME/job-applications"          # fixed output root
```

## Step 5b — optional: style examples and path overrides

Drop one or more previous résumés into `inputs/resume-examples/` and previous letters into `inputs/cover-letter-examples/`. PDF, DOCX, TXT, and Markdown files are supported. Each tailoring run reads them for style, including tone, section naming, bullet structure, organization, and level of detail. They are never treated as sources of facts. Both directories are initially empty, and their contents are gitignored.

If you need to point the engine somewhere unusual, copy the config and edit it:

```sh
cp inputs/paths.example.yaml inputs/paths.yaml
```

Every key is optional; anything omitted falls back to discovery. The file is gitignored, so it is per-machine and does not travel with a clone.

## Step 6 — build your profile

Run `/ijob-profile`. A cold start can parse one or more CVs or résumés, read notes, and collect public GitHub data according to [`skills/ijob-profile/SKILL.md`](../skills/ijob-profile/SKILL.md). If you already maintain a structured career record, derive `profile.json` from that record instead. The record remains the source of truth, and `profile.json` becomes a regenerable index.

Write it to the resolved profile path. The default is the gitignored `$ENGINE/inputs/profile.json`. An external private repository or synced directory is optional.

`/ijob-profile` then offers to set your job-search defaults — the titles you
want, the places, and anything to rule out — and writes them to
`inputs/search-prefs.json`. Skip it and take the defaults; `/ijob-scrape` works
either way, it just asks more questions per run.

**Interests and exclusions are deliberately not in `profile.json`.** The
tailoring engine flattens every string in that file into the text it ranks and
writes from, so an exclusion stored there would be read as a *preference* —
"not Texas" would make Texas jobs rank higher, and "needs visa sponsorship"
would be one bad generation away from a cover letter. Two files, one
conversation.

### Derived mode — if you already keep a career record

If you maintain a richer record of your own (a CV plus notes), you do not have to retype it into `profile.json`. Add a `profile-config.md` describing that record — at `inputs/profile-config.md`, next to the profile, or wherever `profile_config:` in `inputs/paths.yaml` points — and `/ijob-profile` switches to **derived mode**: the record stays the source of truth, `profile.json` becomes a regenerable index of it.

Copy [`inputs/profile-config.example.md`](../inputs/profile-config.example.md) as a starting point. It specifies the four sections the config needs: source files, record conventions, schema extensions, and tagging vocabulary.

---

## Step 7 — job sources, only if you want the job-finding half

Skip this entirely if you bring your own job descriptions. `/ijob-tailor` never
needs it.

Otherwise `/ijob-scrape` needs two things: `python3` on your PATH (standard
library only — nothing to install), and at least one free API key.
[`docs/scrape-source-setup.md`](scrape-source-setup.md) walks through the
signup. No credit card, no paid tier; each API gives 200 requests a month.

Keys go in `inputs/secrets.env`, which is gitignored and should be `chmod 600`.
They are never echoed into a terminal, a log, or a commit.

Two optional scrapers for Indeed and LinkedIn are **off by default** and stay
that way until you enable each one explicitly, after reading the
terms-of-service warning the `enable` command prints. An agent is forbidden
from turning them on for you.

---

## Setting up a second machine

```sh
git clone https://github.com/fbhuiyan2/resume-tailor-agent ~/soft/resume-tailor-agent
git clone git@github.com:<you>/<your-private-profile-repo> ~/.claude/skills/<your-profile-skill>
bash ~/soft/resume-tailor-agent/skills/install.sh

cp ~/soft/resume-tailor-agent/inputs/paths.example.yaml \
   ~/soft/resume-tailor-agent/inputs/paths.yaml
# edit it: set `profile:` (and `profile_config:` if you use derived mode)
# to the paths inside the private repo you just cloned

# then in an agent session: /ijob-setup
```

Two things a clone does not carry, both by design:

- **`inputs/paths.yaml`** — `inputs/` is gitignored, so this never travels. It is the file that tells the engine your profile lives in the private repo rather than at the default `inputs/profile.json`. Skip it and `/ijob-tailor` will not find your profile.
- **The binaries** — fetched per machine by `/ijob-setup`.

Cloning the private repo into `~/.claude/skills/` is what makes it load as a skill in Claude Code and OpenCode. The resume engine itself does not care where it sits, as long as `paths.yaml` points at it — a symlink from `~/.claude/skills/` to a clone kept elsewhere works fine.

---

## Usage

**Say what you want in plain language.** These are playbooks an agent reads, not
command parsers, so there is no syntax to learn and nothing to memorise:

```
/ijob-tailor two pages, research layout, no cover letter
/ijob-tailor ~/jobs/alcf.txt keep it to one page, three references
/ijob-scrape anything at Argonne or Fermilab posted this week
/ijob-shortlist the remote ones again, but drop anything needing citizenship
```

The flags below are a **capability list** — what the playbooks know how to vary.
Use them if you like precision; ignore them entirely and nothing is lost. They
mix freely with plain language in the same line.

| Command | What it does |
|---|---|
| `/ijob-setup` | Fetch or upgrade the two binaries. Once per machine. |
| `/ijob-profile` | Build or rebuild `profile.json` and your search defaults. Re-run after a new paper, project or role. |
| `/ijob-tailor` | A JD in, a tailored PDF and gap report out. Accepts a paste, a path, a URL, several URLs, or a folder `/ijob-scrape` prepared. |
| `/ijob-scrape` | Find postings, store them locally, rank them, hand the ones you pick to `/ijob-tailor`. Costs metered quota. |
| `/ijob-shortlist` | The same narrowing and ranking with discovery off. No network, no quota, run it as often as you like. |

**What `/ijob-tailor` can vary**

| | Flag | Default |
|---|---|---|
| Page budget, enforced as a hard block | `--pages N` | 1 |
| Layout | `--template X` | picked from the page budget |
| References printed | `--ref N` | 1; `--ref 0` drops the section |
| Cover letter | `--cover` / `--no-cover` | asked once, up front |
| Cover letter layout and page cap | `--cl-template X`, `--cl-pages N` | `cover-letter`, uncapped |
| Letter and outreach only, no résumé | `--cl-only` | off |
| ATS-readiness floor (formatting only) | `--target N` | 85 |

One deliberate interaction: `--pages` also picks the default layout, so
`--pages 2` alone gives the two-page layout rather than a stretched one-pager.
Name a template explicitly to override. `--template` alone picks a layout but
still enforces one page.

**What `/ijob-scrape` and `/ijob-shortlist` can narrow by** — work mode, state,
country, city, role class, employer sector, named employer, recency, keywords
(required or excluded), and the work-authorisation requirements a posting
states. The exclusion side adds `--state-exclude`, `--employer-exclude` and
`--not-title`. Full list: `python3 scripts/jobstore.py select --help`, or just
describe what you want.

**The fit floor.** After filtering and ranking, the shortlist measures what is
left against your whole profile and hides anything covering under **35%** of
the requirements the posting states. The agent says so every run, with the
count it hid; "show all" or "floor 20" overrides it for that run, and
`shortlist.fit_floor` in `search-prefs.json` changes the default (`0` turns it
off). Nothing is deleted — a hidden posting is one question away.

This is what stops a computational-materials search handing you a hospital
lab-technician job because the word "scientist" appeared in both. On a real
corpus the genuine match covered 56% and seven irrelevant postings covered
18–27%.

It is **not** the score `/ijob-tailor` reports, and the two are not comparable:
that one grades a finished one-page résumé, this one measures your entire
record. Read it as a ceiling — if everything you have ever done covers 20% of
a posting, no résumé drawn from it will do better.

**The work-authorisation filters never reach a job site.** They run on your
machine after results come back, and the agent is forbidden from asking you
about your own citizenship or visa status — the questions are phrased as
filters on postings, and the answers live in `search-prefs.json`, never in your
résumé profile.

### Naming your own layouts

`resume_template` in `paths.yaml` is a map, so layouts get names instead of paths you have to retype:

```yaml
resume_template:
  default:       "~/record/templates/resume-blue.tex.tmpl"   # used at 1 page
  default_2page: "~/record/templates/resume-2page-blue.tex.tmpl"   # used at 2+
  compact:       "compact"          # -> templates/compact.tex.tmpl
  bw:            "resume"           # the shipped black-and-white one
```

`default` and `default_2page` are the two reserved keys — they are what `--pages` selects between. Everything else is a name you can ask for. Leave the key out entirely and the same rule runs against the bundled layouts: `resume` at one page, `resume-2page` above.

If you pass neither `--cover` nor `--no-cover`, `/ijob-tailor` asks once — **before it does any
work at all**, not after the résumé is built:

```
Want a cover letter and/or recruiter outreach draft for this role? [Y/n]
```

That is the only interruption in a normal run. It sits at the front deliberately: a question
at the end of a long run is one the agent tends to skip.

The cover letter has no default length. It follows whatever `inputs/cover-letter-examples/` shows — a short industry letter or a long research-staff one organized by posting requirement — and only `--cl-pages N` imposes a hard cap.

Note that `--cl-only` skips the ATS accept gate entirely, so nothing on that path is scored or verified. It ships on the no-fabrication rule alone.

---

## Scope

This engine produces **resumes**, one or two pages, ATS-safe. It is not a CV generator — a full academic CV with a complete publication list has different conventions and no page ceiling, and the one/two-page gate here will fight you. Keep the CV in your own LaTeX and use this for resumes.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `/ijob-tailor` not offered | `SKILL.md` must be capitalized exactly; `name` must match the directory name; both `name` and `description` required. |
| Skill found, paths break | `RESUME_TAILOR_HOME` unset and the repo is not at the default path. |
| `TOOL MISSING` / `TECTONIC MISSING` | Binaries are gitignored — run `/ijob-setup` on this machine. |
| First compile hangs | Tectonic is downloading its package cache. One time, ~50 MB. |
| Personal data in `git status` | Something wrote into the engine repo. Outputs belong in `$RESUME_TAILOR_OUT`, the profile in the private repo. |
| `/ijob-scrape` says it needs a profile | By design — discovery spends metered quota and has nothing to rank against without one. Run `/ijob-profile`. Selection over an existing corpus still works. |
| `/ijob-scrape` reports no python3 | Install it. `/ijob-tailor` still works on a pasted or file JD, but not on a URL — fetching a posting runs `scripts/fetch_posting.py`. |
| Monthly quota spent | 200 requests per API per month, tracked in `inputs/scrape/jobs.db`. Fall back to `/ijob-shortlist`, which costs nothing. |
| A job folder tailored against nothing | The posting body was never captured. The engine skips those rather than writing a résumé against a job title; re-fetch from the apply URL in `jd.meta.json`. |
