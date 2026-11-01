# Templates

The bundled files are example layouts, not required formats. Use one as provided, adapt one for your field, or ask your agent to convert the design of an existing résumé into a compatible template. Then tell `/ijob-tailor` which template to use.

| File | Shape |
|---|---|
| `resume.tex.tmpl` | Default. One page. Summary, Skills, Projects, Experience, Education. Industry/software flavoured. |
| `resume-2page.tex.tmpl` | Longer form. Summary, Education, Research Experience, Skills, Highlighted Journal Publications, Leadership & Teamwork Experience, Selected Awards & Honors, References. Research/academic flavoured, and the only bundled layout with a References section (`--ref N`). |
| `cover-letter.tex.tmpl` | Cover letter, moderncv `classic`. Selected with `--cl-template`. |

## The template owns the sections

`/ijob-tailor` reads the `\rsection{...}` calls from whichever template you choose, top to bottom, ignoring `%`-commented lines, and that becomes the expected section list and reading order for the structural verify gate. There is no hardcoded list anywhere in the engine. A section whose profile data is empty is dropped rather than shipped as an empty heading.

So a different field just means a different template. Reorder the sections, rename them, add ones that don't exist here — the gate follows the file.

## Using your own

If you already have a résumé whose design you want to keep, give it to the agent and ask it to reproduce that layout as a `.tex.tmpl` file for this repository. The conversion must preserve the ATS requirements below. Review the generated template before using it for applications.

You can keep a custom template inside this repository or at any private path:

```
/ijob-tailor --template my-layout                 # -> templates/my-layout.tex.tmpl
/ijob-tailor --cl-template my-letter              # cover letter layout
/ijob-tailor --template ~/private/my-resume.tmpl  # any path, including outside this repo
/ijob-tailor --pages 2 --template my-layout       # a 2-page budget on a layout of your choosing
```

Keeping a personal template in a private repo is the recommended pattern — layouts tend to carry personal formatting choices, and `--template` takes a path precisely so it doesn't have to live here.

Retyping those paths gets old, so give them names in `resume_template` in `inputs/paths.yaml`:

```yaml
resume_template:
  default:       "~/private/my-resume.tmpl"        # used at a 1-page budget
  default_2page: "~/private/my-resume-2page.tmpl"  # used at 2 pages or more
  compact:       "my-layout"                       # -> templates/my-layout.tex.tmpl
```

Then `/ijob-tailor` picks the right one from the page budget alone, `--template compact` (or "use the compact layout") picks by name, and a path still works for a one-off. Omit the key entirely and the same page rule runs against the bundled layouts: `resume` at one page, `resume-2page` above — a one-page layout stretched to two pages has no Publications and no References section, which is rarely what was wanted.

## Cover letter templates

`cover-letter.tex.tmpl` uses `moderncv`, which Tectonic fetches on first compile. Three things bite:

- **Use `newtxtext`, not `mathptmx`.** Under XeTeX `mathptmx` leaves the font unresolved (`TU/ptm undefined`) and silently substitutes.
- **The recipient block is removed on purpose.** Stock `moderncv` prints "Hiring Manager / Unit / Organization" above the salutation — three lines the opening paragraph already says, costing about an inch. The template overrides `\makeletterhead` to drop it, along with the date line. Because nothing reads it any more, the template does not call `\recipient` at all.
- **If you restore the stock head, `\recipient` must have non-empty arguments.** Empty ones abort with `LaTeX Error: There's no line here to end.`

The margin floor below applies to resumes, where the scorer runs. Cover letters are not ATS-scored, so layout there is a matter of taste.

## References section (optional)

A template may end with a `\rsection{References}`. When it does, `/ijob-tailor --ref N` sizes it from `profile.references[]`: default 1 (the entry flagged `"default": true`), `--ref 0` drops the section, `N>1` makes the agent ask which referees to use. Templates without the section ignore the flag. Keep References last — a referee block above Education reads as a mistake.

## Rules any template must follow

**Keep the words intact for the extractor.** Every template here carries this block, and a custom one needs it too:

```latex
\tolerance=3000
\emergencystretch=3em
\hyphenpenalty=10000
\exhyphenpenalty=10000
\AtBeginDocument{\fontdimen4\font=0pt}
```

Two failures it prevents, both invisible on the printed page.

*Squeezed spaces.* When TeX compresses a justified line, interword space can shrink below what a PDF text extractor needs to see a word boundary. The line looks fine on screen and extracts as `graphneuralnetworks,machine-learnedinteratomicpotentials` — invisible to any ATS keyword scan.

*Hyphenation.* A word TeX breaks across a line keeps its hyphen in the extracted text: `configu-ration sampling`, `agen-tic`, `develop-ment`. The keyword is printed correctly and still never matches. Both penalties are needed — one for automatic hyphenation, one for breaking at a hyphen the word already has. On the bundled 2-page layout this lifted JD match 60 → 63 with no other change. Real compounds like `fine-tuning` keep their hyphen and stay on one line.

Both fixes cost a little vertical space and buy back the words. Don't reach for `\raggedright` instead: it dodges the space problem, does nothing for hyphenation, and a ragged block beside justified bullets reads as unfinished.

## Layout macros

The bundled templates define four helpers. A custom template does not have to use them, but `/ijob-tailor` checks two of them, so dropping them means dropping the check.

| Macro | What it does |
|---|---|
| `\rsection{Name}` | Section heading plus rule. Ends with `\par`, never `\\` — a `\\` leaves a blank source line rendering as a full empty line between the rule and the content. Also widens its own interword space to 0.33em, because at the default 0.25em some PDF viewers copy the heading back as `LEADERSHIP&TEAMWORKEXPERIENCE`. |
| `\rsummary{...}` | Wraps the Summary paragraph. Justified, and writes `SUMMARY-LINES: N` into the `.log` so the four-line cap is machine-checkable the same way the page budget is. |
| `\rsubgroup{Theme}` | 2-page layouts. A themed workstream inside one role: an open-circle marker plus bold text, indented one step so it reads as a child of the job title instead of a peer. |
| `rsubitems` | The `itemize` belonging to an `\rsubgroup`, indented one step further. A single-focus role takes a plain `itemize` at the margin. |


These are what keep a resume machine-readable. Break them and the ATS gate fails.

- **Margin floor 0.7in.** Below roughly 0.65in the bundled scorer false-detects a multi-column layout — `severity: fail`, automatic gate failure — and the text extraction scrambles: the header sinks into the middle of the document and lines split mid-word. Verified by bisection: 0.50-0.65 broken, 0.70+ clean. If a run reports `multi-column layout` on a single-column template, widen the margin before changing anything else. Never tighten below 0.7in to fit content; cut content instead.
- **Single column.** No `multicol`, no `tabular` for layout.
- **No images, icons, or graphical bullets.** Bullets come from `itemize`.
- **Contact recoverable.** Use `\href{mailto:...}` and `\href{tel:...}` so the scorer can extract email and phone even when they render as plain text. Missing phone costs 5 points, missing LinkedIn or portfolio 3.
- **11pt minimum**, and a Times-clone serif (`newtxtext`) or another font Tectonic bundles.
- **Escape LaTeX specials in visible text:** `\&`, `\%`, `\$`, `\#`, and underscores in URL display text. Unescaped ones either fail the compile or leak into the extraction.
- **Keep `\rsubgroup` indented and on its own paragraph** if your template defines one. A sub-heading that continues a previous line gets swallowed into it and stops being a heading, and flattening it to a flush-left `\textbf{...}` makes it look like another job title. Its `$\circ$` marker was measured against the bundled scorer and costs nothing; a glyph inside bullet *text* is a different matter and stays banned.

## Checking a template before you rely on it

```sh
./tectonic --keep-logs --outdir /tmp/t templates/my-layout.tex.tmpl
grep -o "Output written.*" /tmp/t/my-layout.tex.log     # page count
./tool /tmp/t/my-layout.tex.pdf --json | head -30       # must show no severity:fail
./tool /tmp/t/my-layout.tex.pdf --md /tmp/t/out.md      # header first? sections in order?
```
