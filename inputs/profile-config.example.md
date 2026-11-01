# profile-config — how to derive profile.json from a career record

**This is a template.** Copy it to `inputs/profile-config.md` and edit it to describe your record. If you keep your profile outside the repo, put it next to that profile instead, or name it explicitly with the `profile_config:` key in `inputs/paths.yaml`.

Its presence is what switches `/ijob-profile` into **derived mode**. The skill looks for it at the `profile_config:` path in `inputs/paths.yaml` if that key is set, otherwise beside the resolved `profile.json`. Not found means standalone mode, which parses a CV from `inputs/` instead.

Derived mode exists so you do not maintain the same career facts twice. Your record stays the source of truth; `profile.json` becomes a regenerable index of it, shaped for the engine's tag-overlap prefilter. Never hand-edit a derived `profile.json` to add a fact — edit the record and regenerate, or the two drift and the resume starts citing things the record does not contain.

Delete any section below that does not apply. `/ijob-profile` looks for the four required headings — Source files, Record conventions, Schema extensions, Tagging vocabulary — plus an optional Depth section.

---

## Source files

List every file in the record and what each is authoritative for. Be explicit about which one wins on conflicts.

| File | Authority |
|---|---|
| `references/cv.tex` | Canonical for every list, count, date, and citation. |
| `references/experience.md` | What was personally done in each position. |
| `references/projects.md` | Per-project technical depth. |
| `references/skills-and-tools.md` | Honest depth calibration per skill. |

## Record conventions

Anything a reader needs in order to parse the record correctly. Examples:

- Ordering (e.g. "publication lists are newest-first; `etaremune` counts down").
- How the subject's own name is marked in author lists (e.g. `\underline{Lastname, F.M.}`).
- Where status or state appears and what the values mean (e.g. "status in parentheses at entry end: `(Submitted)`, `(under review)`, `(Accepted, ...)`, absent when published").
- Any abbreviation or shorthand the record uses.

## Schema extensions

The base schema (`profile.example.json`) is industry-shaped: experience, projects, skills, education. If your field needs more, define it here. Academic records typically add:

```jsonc
{
  "publications": [
    { "authors": "", "year": 2026, "title": "", "venue": "",
      "volume": "", "pages": "",
      "status": "published | accepted | under_review | submitted",
      "status_verbatim": "(Accepted, Journal Name.)",
      "first_author": true,
      "tags": [] }
  ],
  "talks":    [ { "title": "", "venue": "", "date": "", "type": "oral|poster|seminar", "tags": [] } ],
  "funding":  [ { "name": "", "amount_usd": 0, "role": "PI|co-PI|author", "year": "", "tags": [] } ],
  "teaching": [ { "role": "", "course": "", "institution": "", "dates": "", "tags": [] } ],
  "service":  [ { "role": "", "organization": "", "dates": "", "tags": [] } ]
}
```

Two rules worth copying verbatim if you add publications:

- `status_verbatim` is copied character-for-character from the record. The tailoring pass prints that string and never paraphrases it. **Promoting "Submitted" to published is fabrication.**
- `meta.counts` stores true totals so a two-page run can print "Total N" truthfully while displaying only a relevant subset.

## Tagging vocabulary

Tag overlap is how the engine prefilters your record down to a working set per job, so this section does more for output quality than anything else in the config. Define your axes explicitly. A research profile might use:

1. **Methods** — the techniques you actually run
2. **Software** — named tools and languages
3. **Domains** — subject areas
4. **Transferable** — what a non-specialist recruiter would call the same work

**Axis 4 is not optional.** Specialist terms rarely appear in postings verbatim. A posting says "molecular simulation", "ML for science", or "distributed computing" where a record says `ReaxFF`, `MLIP`, or `Parsl`. Without transferable tags, a genuinely relevant posting prefilters to nothing and the engine reports a gap you do not have.

Tag publications by method and domain, never by journal.

## Depth (optional)

If the record calibrates how deep each skill goes, say so here and name the field. `/ijob-profile` carries it into `skills.*[].depth` as `expert` | `working` | `familiar`, and the tailoring pass will not present a `familiar` skill as a headline strength.
