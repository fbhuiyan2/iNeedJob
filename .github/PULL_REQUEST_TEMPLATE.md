<!-- Keep this template. Delete the comments, fill the sections. -->

## What
<!-- One sentence. What does this PR change? -->

## Why
<!-- One paragraph. The problem it solves or the improvement it makes. Link the issue if there is one (`Closes #N`). -->

## How tested
<!-- Required for anything beyond doc typos. -->
- [ ] Ran `/ijob-tailor` end-to-end on at least one JD
- [ ] Resume PDF stays within the selected page budget
- [ ] ATS structural verify passed (`tool resume.pdf --json` → no `severity:fail`)
- [ ] `ats.score` ≥ 85 — the formatting floor. **JD-fit is never gated**: a
      low `jd_match` on a posting the profile genuinely does not cover is the
      correct outcome, not a failure to fix
- [ ] No fabrication slipped into bullets — every claim traces to `profile.json`
- [ ] N/A — docs / playbook wording only

<!-- Paste the score line + page count from your test run. Strip personal data. -->

```
score: <paste>
pages: <paste>
```

## Scope check
<!-- See CONTRIBUTING.md → "What this project does NOT want" -->
- [ ] No new external dependencies
- [ ] No build step / glue code introduced
- [ ] No web UI / server / daemon
- [ ] Profile-data files are still gitignored

## Notes for the reviewer
<!-- Anything tricky, anything you're unsure about, anything you want pushback on. Keep it short. -->
