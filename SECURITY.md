# Security Policy

## Scope

This repo is Markdown playbooks, LaTeX templates, two bundled binaries fetched by `/ijob-setup`, and a handful of standard-library Python scripts. There's no server and no auth. It does make network calls at runtime: fetching a posting from a URL, querying a job API with a key from `inputs/secrets.env`, running the opt-in JobSpy scrapers through `uv`, and reading a public GitHub profile during `/ijob-profile`.

Security-relevant concerns in scope:

- **Profile data leakage.** `profile.json` is gitignored — but if any playbook ever writes profile contents into a tracked file or a network request, that's a bug. Report it.
- **Command injection via JD.** `/ijob-tailor` reads JD text and shells out. If a crafted JD can cause arbitrary command execution, report it.
- **LaTeX-side injection.** If a profile field can be crafted to escape the template and execute shell-escape commands during Tectonic compile, report it.
- **Supply chain.** If a `/ijob-setup` download URL can be tricked into fetching a different binary, report it. Same for `scripts/_jobspy_runner.py`, which resolves a third-party package through `uv run --with` at call time.
- **Credential handling.** API keys live in `inputs/secrets.env` (gitignored, `chmod 600`). If any script or playbook echoes a key into a terminal, a log, a corpus row, or an outbound request to anything but the API it authenticates to, report it.
- **Prompt injection via posting text.** Fetched postings are untrusted data. If a crafted posting can get a playbook to treat its contents as instructions — enabling a source, changing a path, writing outside the output folder — report it.

Out of scope:

- Vulnerabilities in the bundled binaries themselves (`tool`, `tectonic`) — report those upstream: [open-ATS](https://github.com/NoahMustafa/open-ATS/security) and [tectonic-typesetting/tectonic](https://github.com/tectonic-typesetting/tectonic/security).
- Output PDFs being parseable by an attacker who already has the file.
- Issues in the user's agentic LLM tool.

## Reporting

Email <fbhuiyan@anl.gov> with:

- A short description of the issue.
- Repro steps (a sample profile / JD if relevant — strip your real personal data first).
- What you think the impact is.

No PGP, no bug bounty, no SLA. This is a side project. I'll acknowledge within a week and patch as soon as I can verify.

**Don't open a public issue for security bugs.** Anything else is fine in [Issues](../../issues).

## Supported versions

`main`. There are no release branches yet.
