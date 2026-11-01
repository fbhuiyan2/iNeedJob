# Contributing

Thanks for showing up. This project is a playbook system — the agent IS the engine and the `.md` files are the program, with thin standard-library Python under `scripts/` for the deterministic parts (fetch a URL, call an API, run SQL). That shapes what contributions look like.

## What you can contribute

| Type | Where | Notes |
|---|---|---|
| Playbook improvements | `skills/*/SKILL.md` | The big ones. Better prompts, tighter rules, fewer ambiguities. |
| Humanizer rules | `references/blacklist.md` | New AI tells, banned phrases. Cite the case if you can. |
| Verb bank additions | `references/verb-bank.md` | Action verbs grouped by intent. No "leverage". |
| LaTeX template | `templates/*.tex.tmpl` | Single-column, ATS-safe. Test the output before PR: it must compile, stay within its page budget, and show no `severity: fail` from the scorer. |
| Bug reports / feature requests | [Issues](../../issues) | Use the templates. |
| Real-world test JDs | [Discussions](../../discussions) | Especially non-tech roles. Helps stress-test no-fabrication. |
| Docs / typos | Anywhere | Lowest barrier. |

## What this project does NOT want

- A glue-code framework (no Bun, no Node, no orchestration layer). The whole point is "agent reads Markdown, shells out". Scripts under `scripts/` stay standard library only, with no build step and nothing to install — if a PR adds one, it's the wrong PR.
- A web UI. Out of scope. The CLI scorer ([open-ATS](https://github.com/NoahMustafa/open-ATS)) has a [live demo site](https://open-ats-site.pages.dev/) if that's what you want.
- Code that bypasses the no-fabrication rule. Non-negotiable.
- New external dependencies. Two binaries fetched by `/ijob-setup`, and `scripts/` on the standard library. The single exception is `scripts/_jobspy_runner.py`, quarantined behind `uv run --with` and a subprocess boundary so the rule holds everywhere else; a PR that adds a second exception needs to argue for it.

## Good first issues

Issues labelled [`good first issue`](../../issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) are scoped for newcomers — usually playbook wording, verb-bank additions, or doc fixes. No LaTeX, no scoring math.

## Workflow

1. Open an issue first if your change is non-trivial (rule change, new playbook, template restructure). Avoids wasted work.
2. Fork → branch (`feat/short-name` or `fix/short-name`) → PR against `main`.
3. **Test against a real run.** If you touched `skills/ijob-tailor/SKILL.md`, run `/ijob-tailor` end-to-end on at least one JD and confirm score + page budget respected. Paste the result in the PR.
4. **Personal data stays out of commits.** Never force-add `profile.json`, credentials, posting corpora, test data, or generated application folders. The tracked `inputs/*.example.*` files are documentation and may be updated.
5. **No AI-written PR descriptions.** This repo's whole point is anti-AI-filler. Write your PR like a human. Run the [humanizer](references/blacklist.md) over it if unsure.

## Commit style

Conventional Commits, lowercase, scope when useful:

```
feat(tailor): add JD-noun mirroring section
fix(template): drop dangling \rsection on empty module
docs(readme): clarify accept-gate threshold
chore: bump open-ATS pin
```

No "Co-authored-by: Claude" or similar. Commits read like a human wrote them, because a human did.

## Local check before PR

Run the deterministic checks relevant to your change:

```sh
python3 -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('scripts/*.py')]"
bash -n skills/install.sh
python3 -I scripts/jobstore.py --root /tmp/ineedjob-check stats
```

If you changed the tailoring playbook or a template, run `/ijob-tailor` from an agent session on at least one JD. Confirm that the PDF stays within the selected page budget, structural verification passes, and `ats.score` meets the configured formatting floor. The JD-match score is reported but never gated.

If you do not have an agentic LLM tool to run the playbooks, say so in the PR and a maintainer will spot-check.

## Questions

Open a [Discussion](../../discussions) for design questions, [Issue](../../issues) for concrete bugs/requests. Don't email.

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Short version: be a person, not a problem.
