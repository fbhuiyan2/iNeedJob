<div align="center">

# Resume Tailor Agent

**A Markdown playbook that turns an agentic LLM into a per-job résumé tailor, without fabricated experience, AI filler, servers, or glue code.**

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Playbook only](https://img.shields.io/badge/playbook-Markdown%20only-blue)](skills/)
[![No fabrication](https://img.shields.io/badge/policy-no%20fabrication-critical)](#non-negotiables)
[![ATS-safe output](https://img.shields.io/badge/output-ATS--safe%20PDF-lightgrey)](#what-you-get-per-job)
[![Powered by open-ATS](https://img.shields.io/badge/powered%20by-open--ATS-orange)](https://github.com/NoahMustafa/open-ATS)

**[Try the underlying scorer in your browser →](https://open-ats-site.pages.dev/)** &nbsp;·&nbsp; **[CLI scorer source](https://github.com/NoahMustafa/open-ATS)**

By **Fakhrul Hasan Bhuiyan**.

</div>

---

> **Interviewer:** So, why do you want this position?
>
> **Applicant:** iNeedJob

Find jobs. Tailor a résumé to each one. Decide where to apply, with an honest report of where you fall short.

Give the agent a job description, a file, or a posting URL. It returns an ATS-safe résumé tailored to that role and a gap report identifying requirements your profile does not meet. Choose a one-page or two-page layout, and add a cover letter if you want one. The engine does not invent experience. If you are underqualified, it reports the score and explains why instead of adding unsupported keywords to a bullet. It can also find and rank job postings for you.

The repo contains Markdown playbooks, thin scripts, and LaTeX templates. Your agent, whether Claude Code, OpenCode, Cursor, or another supported harness, reads the playbooks and calls two downloaded binaries. `tool` handles ATS scoring, and `tectonic` compiles the LaTeX. Every tailoring run reads one profile file. That file can be maintained directly or generated from a richer career record kept elsewhere.

---

## Getting started

The initial setup has three parts. Choose an agent, build your profile, and add a job source if you want the job-discovery feature. After that, find jobs or bring your own posting and generate the application documents.

### 1. Use an agent

You do not need to install or build the project by hand. Start a session in an agentic LLM harness with file and shell access, such as Claude Code, OpenCode, Codex, or Cursor. Then say:

> Clone https://github.com/fbhuiyan2/resume-tailor-agent and set it up for me.

The agent reads [`AGENTS.md`](AGENTS.md) and handles the setup:

```
Cloned to ~/soft/resume-tailor-agent

Installing skills -> ~/.claude/skills
  /ijob-setup  /ijob-profile  /ijob-tailor  /ijob-scrape  /ijob-shortlist
Installing skills -> ~/.codex/skills
  …and every other harness directory found under $HOME

Engine path configured: <directory where the repository was cloned>

Fetching binaries…
  tool       ✓   (ATS scorer)
  tectonic   ✓   (LaTeX compiler)

Setup done. Next: /ijob-profile to build your profile.
```

During setup, the installer copies each playbook into the skill directories it finds under `$HOME`. It records the repository's actual location, so you can use the skills from any working directory. If your harness is not supported by the installer, the agent can still read the playbooks directly from the clone.

> **Restart your harness once it finishes.** The slash commands won't appear
> until you do. That is never a blocker — the playbooks are plain Markdown, so
> an agent can read them straight from the clone and follow them as written.

### 2. Build your profile

```
/ijob-profile
```

Provide one or more CVs, résumés, or career records. The agent combines the source material, offers to include relevant public GitHub repositories, and asks only when something is genuinely ambiguous. You can add freeform notes for work that is missing from the documents.

```
Reading inputs/cv.pdf … 14 positions, 23 publications, 9 projects
GitHub @you … 31 public repos, 6 look substantial. Include them? → yes

Two things I couldn't infer:
  1. "Parsl workflow orchestration" — expert, working, or familiar?
  2. Which reference should be the default on a one-page résumé?

Wrote inputs/profile.json — 9 projects, 23 publications, 61 tagged bullets.
```

It then offers to set up your job-search defaults, including target titles, locations, and exclusions. You can accept the defaults and revise them later or answer the questions immediately. These preferences are saved in `inputs/search-prefs.json`.

You can also provide previous résumés and cover letters as style references. The engine uses them for tone, section naming, bullet structure, organization, and level of detail. It does not treat them as sources of facts. Place them in `inputs/resume-examples/` and `inputs/cover-letter-examples/`, or configure other private directories in `inputs/paths.yaml`.

By default, personal files stay in the gitignored `inputs/` directory and are not committed. You can instead point the engine to a private repository or synced directory.

### 3. Add a job source — only if you want the job-finding half

Skip this if you'll bring your own job descriptions. Otherwise you need one free API key: see **[docs/scrape-source-setup.md](docs/scrape-source-setup.md)** for the signup walkthrough. No credit card, no paid tier.

### 4. Find jobs

```
/ijob-scrape  find me computational materials jobs at national labs,
              posted this month, nothing needing a clearance
```

It shows you what it's about to spend before spending it:

```
0 postings held · discovery on (3 sources) · ranking against inputs/profile.json

Searching for:
  Positions   computational materials scientist · ML research scientist
  Where       Illinois · remote or hybrid
  Excluding   postings stating clearance or export-control requirements
  Queries     3 requests of your 200 remaining on JSearch
Go ahead? → yes

JSearch 31 · LinkedIn 18 · Indeed 9 · 58 new, 0 already held

Showing 8 postings: 7 cover at least 35% of their stated requirements, and 1
was too thin to score. 15 scored below the floor and are hidden.

 #  Employer                     Title                               Where       Posted  Fit
 1  Argonne National Laboratory  Postdoc, ML Interatomic Potentials  Lemont IL   3d      56%
 2  SES AI                       Computational Materials Scientist    Boston hyb  6d      41%
 3  Oak Ridge National Lab       Computational Scientist, Materials   Oak Ridge   8d      39%
 …
58 in the corpus · 41 matched your filters · 23 after keywords · 4 hidden by
your saved filters · 15 below the fit floor · 1 too thin to score · showing 8

How many do you want to work through?
```

### 5. Get the tailored documents

> rows 1–12

```
12 folders ready in job-applications_20261023/. 1 page, cover letter, target ATS 85.
Say if you want something different — otherwise I'll start. → go

[ 1/12] Argonne · Postdoc ML Interatomic Potentials … ATS 100, JD 71, 1pp ✓
[ 2/12] Oak Ridge · Computational Scientist, Materials … ATS 100, JD 68, 1pp ✓
[ 3/12] SES AI · Computational Materials Scientist … posting body was never
        captured — skipped rather than tailoring against a job title alone
…
Shipped 11 of 12.

Strongest fits: Argonne (71), Oak Ridge (68), NREL (66)
Gap that repeated across 7 of them: no production Kubernetes experience.
```

Each folder holds `resume.pdf`, `cover-letter.pdf`, the full posting with its apply URL, and a gap report. You apply — this engine never submits anything on your behalf.

**That's the loop.** After the first week your corpus has a few hundred postings in it, and `/ijob-shortlist` re-ranks them for free, as often as you like:

```
/ijob-shortlist  anything remote I haven't looked at yet, last two weeks

9,412 postings held · selection only, nothing fetched
284 matched your filters · 61 after keywords · showing 25
```

---

## The five commands

| | What it's for | How often |
|---|---|---|
| **`/ijob-setup`** | Fetches the two binaries, detects your OS and architecture, and confirms that each binary runs. | once per machine |
| **`/ijob-profile`** | Builds `profile.json` from one or more CVs, résumés, career records, notes, and optional GitHub data. It also creates your search defaults. Re-run it after a new project, paper, or role. It shows the changes and never silently deletes existing information. | once, then occasionally |
| **`/ijob-tailor`** | A job description in, a tailored PDF and a gap report out. Takes a pasted JD, a file path, a URL, several URLs, or a folder `/ijob-scrape` prepared. | per job, or per batch |
| **`/ijob-scrape`** | Finds postings, stores them locally, ranks them against your profile, and hands the ones you pick to `/ijob-tailor`. API discovery uses metered quota. Optional JobSpy sources use your network connection instead. | once or twice a day |
| **`/ijob-shortlist`** | The same narrowing and ranking, with discovery switched off. Touches no network, costs nothing. | as often as you like |

The standard setup requires `python3` on your PATH. The installer uses it to configure the skills, `/ijob-profile` uses it to build the profile-scoring PDF, and the discovery commands use the Python scripts. `/ijob-tailor` also uses Python when fetching a posting URL. The scripts use only the standard library.

---

## Ask in plain language

You do not need to learn command-line syntax. Tell the agent what you want in ordinary language:

```
/ijob-tailor two pages, research layout, no cover letter
/ijob-tailor ~/jobs/alcf.txt keep it to one page and give me three references
/ijob-tailor <paste a JD> cover letter too, cap it at one page
/ijob-scrape  anything at Argonne or Fermilab, posted this week
/ijob-shortlist  show me the remote ones again, but drop anything needing citizenship
```

The tables below list the available options. Advanced users may use the corresponding command-line flags, but plain-language requests work the same way.

<details>
<summary><strong>What <code>/ijob-tailor</code> can vary</strong></summary>

| Capability | Flag, if you want it | Default |
|---|---|---|
| Page budget — a hard block, never exceeded | `--pages N` | 1 |
| Which layout | `--template X` | picked from the page budget |
| How many references to print | `--ref N` | 1, or 0 on layouts without a References section |
| Cover letter on or off, decided up front | `--cover` / `--no-cover` | it asks once before tailoring and document generation |
| Cover letter layout and length cap | `--cl-template X`, `--cl-pages N` | `cover-letter`, no cap |
| Letter and outreach only, no résumé | `--cl-only` | off |
| ATS-readiness floor (formatting only) | `--target N` | 85 |

The bundled `resume` layout is designed for one page, and `resume-2page` is a research-oriented two-page layout with sections for publications, awards, and references. The page budget selects the matching bundled layout unless you request another one.

You can also keep your current résumé design. Give the agent your résumé and ask it to convert the layout into a repository-compatible template. Store the resulting template anywhere you prefer, including a private directory, and name it in `inputs/paths.yaml`. Layout names resolve against your `resume_template` map first and then [`templates/`](templates/). The agent confirms the resolved layout and page budget before writing. See [`templates/README.md`](templates/README.md) for the template requirements.

</details>

<details>
<summary><strong>What <code>/ijob-scrape</code> and <code>/ijob-shortlist</code> can narrow by</strong></summary>

| Capability | Flag, if you want it |
|---|---|
| Remote, hybrid, on-site | `--work-mode remote,hybrid` |
| State, country, or a city | `--state IL` · `--country US` · `--location chicago` |
| Kind of role | `--role postdoc,research,faculty,engineering,…` |
| Kind of employer | `--sector national_lab,university,company,…` |
| A named employer | `--employer argonne` |
| How recent | `--since 30` |
| Keywords it must mention, or must not | `--kw "machine learning"` · `--not lecturer` |
| Work-authorisation requirements the posting states | `--auth-exclude citizen,clearance,no_visa_sponsor,…` |
| Exclusions | `--state-exclude TX` · `--employer-exclude X` · `--not-title lecturer` |
| How many to show | `--limit 25` |

**The work-authorisation filters never reach a job site.** They are applied on your machine after results come back. The agent is also forbidden from asking you about your citizenship or visa status — the questions are phrased as filters on postings, and the answers live in `search-prefs.json`, never in your résumé profile.

</details>

---

## What you get per job

```
<output folder>/
├── resume.pdf            # ATS-safe, within the page budget
├── resume.tex            # the LaTeX it was built from
├── resume.md             # extracted text used for structural verification
├── recommendations.md    # gap report (always) + cover letter and outreach (opt-in)
├── cover-letter.tex      # only when a letter was written
├── cover-letter.pdf      # only when a letter was written
├── score.json            # ATS readiness + JD-match breakdown
├── jd.txt                # normalized job description used for scoring
├── jd.meta.json          # role, employer, location, source, and URL metadata
├── job-info.md           # full posting and apply URL for /ijob-scrape batches
└── run.json              # what shipped and why
```

**Output location:** If you provide a JD file, the output is created beside it. Jobs selected through `/ijob-scrape` stay in the batch folder. Other runs use `./resume-agent-output_{company}-{role}/`. Set `output_root` in `inputs/paths.yaml` if you want one fixed output directory. Outputs are never written inside the engine repository.

A normal run delivers the résumé after it passes the structural and ATS checks and includes every coverable requirement. If further honest revision cannot close the remaining gaps, the engine may deliver a clearly labeled best-effort version and record the unresolved items in `recommendations.md`. The JD-match score is reported but is not a pass threshold. A low score usually means that the profile lacks required experience, which cannot be fixed honestly through rewriting.

---

## Requirements

| | |
|---|---|
| Harness | Any agentic LLM tool with file + shell access (Claude Code, OpenCode, Cursor, Aider, …) |
| OS | Linux (x86_64 or arm64) and macOS (arm64). Windows x86_64 binaries are available, but the complete workflow currently requires a POSIX-compatible environment such as WSL; native PowerShell support is incomplete. Other architectures require building from source. |
| Disk | ~150 MB after `/ijob-setup` |
| Network | `/ijob-setup` to fetch the binaries, Tectonic's one-time LaTeX package cache on first compile, and thereafter only what you ask for: fetching a posting from a URL, a job search, or reading a public GitHub profile during `/ijob-profile`. A paste-in tailoring run after setup needs none. |
| Python | `python3` is required for the standard installer, profile generation, discovery, shortlisting, and URL intake. The repository scripts use only the standard library. |
| Accounts | All optional. A GitHub username helps `/ijob-profile`; one free API key enables job discovery. |

No Docker, no Node, no build step. The two binaries are self-contained.

---

## Disclaimer

This software is provided "as is", without warranty of any kind, under the terms of the [LICENSE](LICENSE). Neither the repository nor its authors or contributors are responsible for how it is used or modified, for any breach of a third party's terms of service arising from that use, or for any consequence of it.

Most sources `/ijob-scrape` can use are sanctioned — public APIs, first-party keys, or vendors that do the collection on their own infrastructure. Two are not: the optional JobSpy scrapers for Indeed and LinkedIn, which run from your machine on your IP and are **off by default**. Each is enabled only by an explicit, per-site opt-in taken after reading the warning the `enable` command prints. Whether to enable them, and the consequences of doing so, are yours alone. Nothing here is legal advice.

---

## Non-negotiables

1. **No fabrication.** Every claim on the PDF traces back to `profile.json`. If a JD demands experience that isn't in your profile, it goes to the gap report — never into a bullet.
2. **Accept gate.** A normal run ships after structural verification, zero ATS failures, and closure of every profile-coverable gap. If further revision cannot improve the document without fabrication, the engine labels the output as best effort and logs what remains unresolved.
3. **Humanizer at write time.** Every line you read passes through [`references/blacklist.md`](references/blacklist.md) — no em-dash punctuation, no "leverage", no chatbot ceremony. Longer prose also follows [`references/writing-style.md`](references/writing-style.md).
4. **The profile is the tailoring source.** Every generated claim must appear in `profile.json`. In derived mode, the profile is regenerated from the authoritative career record. Re-run `/ijob-profile` when the record changes.
5. **Nothing is applied to on your behalf.** The engine produces documents and an apply URL. A human applies. There is no autosubmit and there will not be one.

---

## Does it actually work

| Role tested | Field | ATS | JD match | Verdict |
|---|---|---|---|---|
| Junior Data Developer | tech, strong fit | 100/100 | 57/100 | ceiling = sector + startup-history gaps |
| Data Engineer (mid) | tech, strong fit | 100/100 | 72/100 | ceiling = Azure / AWS / LLM-RAG gaps |
| Data Quality Engineer | tech, niche stack | 100/100 | 77/100 | ceiling = Azure Databricks / PySpark / SAP gaps |
| Senior Data Engineer | tech, junior profile | 100/100 | 58/100 | flagged "don't apply at this level" |
| Junior Accountant | non-tech, no fit | 100/100 | 45/100 | refused to fabricate; 28% on real financial work |

Scores scale with real qualification, not iteration count. ATS readiness is 100/100 across all of them — the formatting engine is solid regardless of fit. External validation: a strong-fit run hit **100% on Jobscan** and **92% on MyCVCreator**; the bundled scorer is stricter than both.

---

## Where to read more

**If you're using it:**

| | |
|---|---|
| [docs/scrape-source-setup.md](docs/scrape-source-setup.md) | Getting the free API keys, what each source is good at, what was rejected and why |
| [templates/README.md](templates/README.md) | Writing your own layout, and the ATS rules any template must follow |
| [docs/tool.md](docs/tool.md) | The bundled ATS scorer's own documentation |

**If you're pointing an agent at it, or changing it:**

| | |
|---|---|
| [AGENTS.md](AGENTS.md) | The agent-facing entry point — what "clone this and set it up" means, and the rules for working on the repo |
| [docs/how-to-setup.md](docs/how-to-setup.md) | The long-form install reference an agent follows: portable paths, a second machine, a private profile repo, environment variables, troubleshooting |
| [`skills/*/SKILL.md`](skills/) | The playbooks. The main skills are readable directly from the clone; `/ijob-shortlist` delegates to `/ijob-scrape`. |
| [`references/`](references/) | The writing rules the tailoring pass reads — verb bank, humanizer blacklist, prose voice |
| [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Contributing, reporting a vulnerability, behaving like a person |

---

## Architecture

```
  /ijob-scrape ──┐                                        metered
                 ├──► ranked shortlist ──► you pick N ──► /ijob-tailor ──► PDFs
  /ijob-shortlist┘                                        free
         │                                                      │
         └── local SQLite corpus: every posting ever seen,       └── profile.json
             with its body when captured, so selection avoids        is the only
             re-fetching                                              tailoring input
```

Inside one tailoring run:

```
 ┌───────────────────────────────────────────────────────────────┐
 │  HARNESS — any agentic LLM tool, reading skills/*/SKILL.md     │
 │    1. load profile.json                                        │
 │    2. read the JD (path, URL, paste, or prepared folder)       │
 │    3. select relevant modules by tag overlap + judgment        │
 │    4. write resume.tex from the chosen template                │
 │    5. tectonic resume.tex → resume.pdf                         │
 │    6. tool resume.pdf --md → structural verify                 │
 │    7. tool resume.pdf --jd jd.txt --json → score               │
 │    8. accept gate? no → targeted edit → back to 5              │
 │    9. write recommendations.md (gap report + opt-in extras)    │
 └───────────────────────────────────────────────────────────────┘
```

No daemon, no background loop, no orchestration framework. **The agent is the engine.** The Markdown playbook is the program, and the agent is the runtime. The same playbooks can therefore be followed by different agentic harnesses.

---

## Repo layout

```
resume-tailor-agent/
├── README.md                       # user-facing — this file
├── AGENTS.md · CLAUDE.md           # agent-facing entry point
│
├── skills/                         # one SKILL.md per command
│   ├── ijob-tailor/      ijob-profile/     ijob-setup/
│   ├── ijob-scrape/      ijob-shortlist/
│   └── install.sh                  # installs them into every harness found
│
├── scripts/                        # stdlib-only Python behind /ijob-scrape
│   ├── jobstore.py                 # the SQLite corpus: store, filter, rank, brief
│   ├── search_own.py               # the metered APIs
│   ├── search_jobspy.py            # the opt-in scrapers, off by default
│   ├── fetch_posting.py            # one URL → one posting folder
│   ├── profile_pdf.py              # the whole profile → one PDF, for scoring
│   └── score_fit.py                # requirement coverage, and the shortlist floor
│
├── templates/                      # bundled default layouts and customization examples
│   ├── README.md                   # how to write your own + the ATS rules
│   ├── resume.tex.tmpl             # default, one page
│   ├── resume-2page.tex.tmpl       # longer form, References last
│   └── cover-letter.tex.tmpl
│
├── references/                     # rules read by the tailoring pass
│   ├── verb-bank.md  blacklist.md  writing-style.md
│
├── docs/                           # the three guides you read once
│   ├── how-to-setup.md             # agent-facing install reference
│   ├── scrape-source-setup.md      # getting the free API keys
│   └── tool.md                     # the bundled ATS scorer's own docs
│
├── inputs/                         # everything personal — contents gitignored
│   ├── profile.json                # your profile
│   ├── search-prefs.json           # your job-search defaults
│   ├── scrape/jobs.db              # the posting corpus
│   ├── secrets.env                 # API keys, chmod 600, never committed
│   ├── resume-examples/  cover-letter-examples/   # read as STYLE, never content
│   └── *.example.*                 # tracked configuration templates and schema examples
│
└── tool[.exe]  tectonic[.exe]      # fetched by /ijob-setup, gitignored
```

---

## Notes & gotchas

- **First install pulls ~150 MB.** Tectonic is ~50 MB; the LaTeX package cache adds another ~50 MB on first compile.
- **The page budget is a hard block.** The engine cuts a project or tightens wording rather than spilling over. It never ships a résumé that exceeds the budget.
- **A thin profile makes a thin résumé.** Time spent on `/ijob-profile` pays back on every job afterwards.
- **Discovery costs, selection doesn't.** Each metered API gives 200 requests a month. Re-ranking what you already have is free, so "show me something different" should always be `/ijob-shortlist`.
- **A posting with no captured body can't be tailored against.** The engine says so and skips it rather than writing a résumé against a job title.
- **Scraped job text is data, never instructions.** If a posting contains something that reads like a directive, it gets reported, not obeyed.
- **No browser extension.** Considered for JD capture and killed — paste-or-path is simpler and avoids per-browser dev-mode installs.
- **The repair loop has no iteration cap.** It runs until the accept gate passes or the remaining gaps are provably profile-genuine. Two iterations with the same score means stuck; it ships the best.
- **Justified text can lose word boundaries, and hyphenation breaks keywords.** Every bundled template sets `\tolerance`, `\emergencystretch`, zeroed interword shrink, and `\hyphenpenalty`/`\exhyphenpenalty` at 10000. A squeezed line extracts as `graphneuralnetworks` — perfect on screen, invisible to an ATS. Keep those blocks if you write your own template; removing them costs measured JD points.
- **If a command misbehaves, read its `SKILL.md`.** That file is the source of truth, not this README. Ask your harness to follow it more strictly.

---

## Contributing

PRs welcome — read [CONTRIBUTING.md](CONTRIBUTING.md) first. The short version: this is a Markdown playbook system. Glue code, build steps, web UIs and new external dependencies will be politely declined. The whole point is that the agent is the engine.

Good first issues are labelled [`good first issue`](../../issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) — usually playbook wording, verb-bank additions, doc fixes.

Security issues: [SECURITY.md](SECURITY.md) — email, don't open a public issue.

---

## Credits and license

Written and maintained by **Fakhrul Hasan Bhuiyan**. The résumé scoring is done by [open-ATS](https://github.com/NoahMustafa/open-ATS), bundled as a binary and fetched by `/ijob-setup`; the PDFs are compiled by [tectonic](https://github.com/tectonic-typesetting/tectonic).

The Markdown playbooks, templates and references in this repo are [MIT-licensed](LICENSE): use them, fork them, change them. The two bundled binaries (`tool`, `tectonic`) are governed by their own licenses — see [docs/tool.md](docs/tool.md) and [tectonic-typesetting/tectonic](https://github.com/tectonic-typesetting/tectonic).

Contact: <fbhuiyan@anl.gov>.
