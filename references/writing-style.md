# Writing style — how prose in this repo should read

`blacklist.md` says what never to write. This file says how to write the rest. Where they overlap, `blacklist.md` wins, because it is the preventive ruleset the scorer's writing-advice checks mirror.

Scope: cover letters, outreach, gap reports, and any longer-form document this repo grows into. Résumé bullets have their own tighter rules in the `/ijob-tailor` playbook §4; the principles here still apply, the document-type sections below do not.

## Hard rules

1. **No em dashes as punctuation.** Rewrite with commas, parentheses, semicolons, or two sentences. Exempt: date ranges (`Jan 2024 -- Sep 2025`).
2. **One idea per sentence.** Split any sentence carrying two independent ideas. Long sentences are the most common way technical prose becomes unreadable.
3. **Limit colons.** If a colon would introduce a long explanation or list, use a separate sentence. A bold run-in heading followed by a colon is fine, that is structure rather than punctuation.
4. **Keep tense consistent.** Follow whatever tense the surrounding document established. Do not drift mid-paragraph.
5. **Define an acronym only if it is used again.** Define at first use (`density functional theory (DFT)`), never twice, and never at all for an acronym that appears once. When editing existing text, keep the conventions already there.
6. **Never introduce a claim the source does not support.** No invented mechanisms, results, numbers, citations, or technical details. In this repo the source is `profile.json`.
7. **Preserve LaTeX and technical notation.** Citation commands, equations, variables, units, labels: leave them alone unless they are wrong.
8. **Do not over-edit.** Asked to polish, make the minimum change that improves clarity, grammar, flow, precision, or concision. Text that is already good stays.

## Voice

Concise, precise, professional. Prefer:

- clarity over rhetorical flourish
- precision over verbosity
- short to medium sentences
- direct statements
- explicit logical transitions
- restrained claims
- specific technical language over generic description

Cut adjectives that carry no information: *remarkable*, *groundbreaking*, *revolutionary*, *novel*, unless the word is doing real work.

Concrete preferences:

- "The model reproduced X" beats "The model was found to be capable of reproducing X".
- "using" beats a page of *through* and *via*.
- State a knowledge gap in one sentence, not three.

## Terminology discipline

Near-synonyms are usually not synonyms, and collapsing them is the fastest way to look like you do not know the field. Keep the distinctions the field keeps, and preserve the author's term when it is deliberate.

Worked examples from computational science, as a pattern for any domain:

- DFT is an electronic-structure method, not an interatomic potential.
- Classical force fields and MLIPs are distinct categories of interatomic potential.
- Reactive and non-reactive force fields are not interchangeable.
- A foundation MLIP and a fine-tuned MLIP are different objects.
- Fine-tuning is not active learning.
- Training, inference, workflow orchestration, and workflow execution are four different things.
- HPC schedulers, workflow executors, and workflow orchestrators do different jobs.

## Active voice

Active voice throughout. Everything this repo produces is something a reader evaluates you on, and "Was responsible for X" is never the right sentence there.

Journal-manuscript conventions are deliberately out of scope here. Tense and voice in a manuscript are a house-style and personal-preference matter, they vary by journal, and encoding one author's choice in a shared repo would be wrong. Keep those in your own writing agent.

## Document types

**Cover letters and job materials.** Professional and confident, never inflated. Confident means the letter may say outright that a piece of work was difficult, that the applicant owned it, or that they are well suited to the role; inflated means adjectives doing the work that evidence should ("world-class", "perfect fit", "highly motivated"). Specific over generic: name the project, the method, and the outcome. Tailor to the posting and the audience. Every claim traces to the record. The opening and closing stay short; the body is where the evidence goes.

**Outreach.** One sentence naming the role and how you found it, one on the strongest evidence match, one asking for a next step. Nothing else.

**Gap reports.** Plain and specific. Name the gap, name the closest real evidence, name the ramp. No spin, and no framing a gap as a strength.

**Review rather than rewrite.** Name the problem, explain it in a sentence, propose a concrete revision. Do not rewrite the whole text when asked for an opinion on it.

## Self-check before returning text

Reread the output for: grammar, tense consistency, acronym consistency, technical meaning preserved, logical flow, concision, and every hard rule above plus `blacklist.md`.

If a requested revision would change the technical meaning, ask instead of silently changing the claim.
