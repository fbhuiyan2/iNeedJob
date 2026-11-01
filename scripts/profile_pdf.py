#!/usr/bin/env python3
"""Render the whole of profile.json to a PDF the ATS scorer will accept.

    python3 -I profile_pdf.py [--profile PATH] [--out PATH] [--tex-only]

This is not a resume and is never sent to anyone. `tool` refuses any input
that is not .pdf or .docx, so scoring a job description against the profile
needs the profile in one of those formats. That is the whole reason this
exists.

Uncurated in content, fixed in shape. Every bullet, skill, publication and
award in the profile goes in -- there is no selection step and no page budget,
because the point is an upper bound: if everything the person has ever done
cannot match a posting, no tailored one-page subset of it will either. That is
what makes the number worth putting a floor on.

The shape is fixed because the scorer needs it. It reconstructs sections from
extracted text, so the output carries real SUMMARY / SKILLS / EXPERIENCE /
PROJECTS / EDUCATION headings, one column, no graphics -- and an unusually
wide page, for the reason given at PREAMBLE. A raw JSON dump parses as noise.

Measured against the scorer's own `--md` export, every one of the 490 strings
in a real profile survives the round trip to PDF and back, across all of it --
publications, talks, awards and funding included. Nothing is truncated.

Two things are deliberately left out:

  * `keyword_bank` and the per-item `tags` arrays. They are derived indexes
    over content that is already here, so including them adds no claim the
    profile does not make but does inflate gazetteer hits -- which would
    quietly raise every score and miscalibrate the floor.
  * `references`. Other people's names and email addresses have no bearing on
    whether a posting fits, and a scoring artifact is not a place to copy them.

Unknown top-level sections are rendered generically rather than dropped, so a
profile extended through profile-config.md (publications, talks, funding, and
whatever a given field needs) still scores against everything it holds.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)

# Rendered by a named handler below, in this order. Everything else in the
# profile follows generically, in the order the file lists it. `meta` is in
# the list so the generic pass skips it: it records which importer ran and
# when, and makes no claim about the person.
EXPLICIT = ("meta", "identity", "summary_seeds", "skills", "experience",
            "projects", "education")
# Index artifacts and third-party contact details. See the module docstring.
OMIT = ("keyword_bank", "references", "tags")

# A very wide page, which is the whole trick. The scorer reconstructs
# sections from the extracted text, and reads any short line starting with a
# letter as a heading. On letter paper every bullet that wrapped left a short
# tail behind -- "AI/ML model development", "College London, ORNL" -- and each
# one became a fake section: 11 real headings against 11 invented ones.
# Measured against the scorer's own --md export, letter gives 11 strays, 13in
# three, 20in one, and 26in none. Nobody looks at this file, so the page can
# be whatever shape makes the parse correct.
PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage[paperwidth=26in,paperheight=11in,margin=0.5in]{geometry}
\usepackage[T1]{fontenc}
\usepackage{enumitem}
\setlist[itemize]{leftmargin=1.2em,topsep=2pt,itemsep=0pt,parsep=0pt}
\pagestyle{empty}
\raggedright
\setlength{\parindent}{0pt}
\renewcommand{\familydefault}{\rmdefault}
"""


# Latin Modern under T1 has no glyph for anything past Latin-1, and XeTeX
# drops those characters with only a "Missing character" note in the log --
# so a bullet reading "accuracy >= 3x" silently became "accuracy 3x". Map the
# symbols that actually turn up in a technical profile to ASCII; anything
# still unrepresentable becomes a space, so neighbouring words do not fuse.
_ASCII = {
    "\u2265": ">=", "\u2264": "<=", "\u2260": "!=", "\u2248": "~=",
    "\u00b1": "+/-", "\u00d7": "x", "\u00f7": "/", "\u221e": "infinity",
    "\u2192": "->", "\u2190": "<-", "\u2194": "<->", "\u21d2": "=>",
    "\u2013": "--", "\u2014": "---", "\u2212": "-", "\u00b7": ".",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2026": "...", "\u2032": "'", "\u2033": '"', "\u00b0": " deg",
    "\u00b5": "micro", "\u03bc": "micro", "\u2080": "0", "\u2081": "1",
    "\u2082": "2", "\u2083": "3", "\u2084": "4", "\u00b2": "2",
    "\u00b3": "3", "\u00b9": "1", "\u2070": "0", "\u2074": "4",
    "\u00a0": " ", "\u2009": " ", "\u202f": " ", "\u200b": "",
}


def to_latin1(s):
    """Everything Latin Modern can set, and nothing it cannot.

    Returns (text, dropped) so the caller can report what was lost rather
    than pretend the profile rendered whole.
    """
    out, dropped = [], 0
    for ch in s:
        if ch in _ASCII:
            out.append(_ASCII[ch])
            continue
        if ord(ch) < 0x100 or ch in "\n\t":
            out.append(ch)
            continue
        folded = unicodedata.normalize("NFKD", ch)
        keep = "".join(c for c in folded if ord(c) < 0x100
                       and not unicodedata.combining(c))
        if keep.strip():
            out.append(keep)
        else:
            out.append(" ")
            dropped += 1
    return "".join(out), dropped


DROPPED = [0]          # characters no glyph could render, reported in --json


def tex_escape(value):
    """LaTeX-safe. Profile text is arbitrary: & in company names, % in
    metrics, _ in identifiers, $ in funding figures."""
    s = "" if value is None else str(value)
    s, lost = to_latin1(s)
    DROPPED[0] += lost
    out = []
    for ch in s:
        if ch in "&%$#_{}":
            out.append("\\" + ch)
        elif ch == "~":
            out.append(r"\textasciitilde{}")
        elif ch == "^":
            out.append(r"\textasciicircum{}")
        elif ch == "\\":
            out.append(r"\textbackslash{}")
        else:
            out.append(ch)
    return "".join(out)


def strings_of(node):
    """Every string under `node`, in order, skipping the omitted keys.

    Shape-agnostic on purpose: a profile extended for a field this repo has
    never seen still renders, because nothing here enumerates its keys.
    """
    out = []
    if isinstance(node, str):
        if node.strip():
            out.append(node.strip())
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        out.append(str(node))
    elif isinstance(node, dict):
        for k, v in node.items():
            if k in OMIT:
                continue
            out.extend(strings_of(v))
    elif isinstance(node, (list, tuple)):
        for v in node:
            out.extend(strings_of(v))
    return out


def section(title, body_lines):
    # Escaped like any other profile string: the generic pass in build_tex
    # turns unknown top-level keys into headings, and a key such as "r&d"
    # produced \section*{R&D}, which fails the compile.
    if not body_lines:
        return []
    return ([r"\section*{%s}" % tex_escape(str(title).upper()),
             r"\vspace{-0.6em}\hrule\vspace{0.4em}"] + body_lines)


def bullets(items):
    items = [i for i in items if i]
    if not items:
        return []
    # `\item {}` not `\item `: a bullet beginning with "[" -- a numbered
    # citation, say -- is otherwise read as the item's optional label, so
    # "[1] Smith et al." renders as "1 Smith et al." with no bullet, and an
    # unclosed bracket fails the compile outright.
    return ([r"\begin{itemize}"] +
            [r"  \item {}%s" % tex_escape(i) for i in items] +
            [r"\end{itemize}"])


def render_header(profile):
    """Name, then contacts, then every other scalar on `identity`.

    The last part matters: a fixed key list dropped `publishes_as` and
    `work_authorization` outright, and the omission hid behind a fidelity
    check because the publication list happened to repeat the same string.
    """
    ident = profile.get("identity") or {}
    contact = ident.get("contact") or {}
    name = ident.get("name") or "Profile"
    # Preferred order first, then every other key the profile carries. A
    # fixed list silently drops google_scholar, orcid and whatever a given
    # field uses, and this dump is not supposed to drop anything.
    first = ("email", "phone", "location", "linkedin", "github", "website")
    rest = [k for k in contact if k not in first and k not in OMIT]
    bits = []
    for k in list(first) + rest:
        bits.extend(strings_of(contact.get(k)))
    for k, v in ident.items():
        if k in ("name", "contact") or k in OMIT:
            continue
        bits.extend(strings_of(v))
    line = " \\quad ".join(tex_escape(b) for b in bits)
    return [r"{\LARGE \textbf{%s}}" % tex_escape(name), "", line, "",
            r"\vspace{0.6em}"]


def render_skills(skills):
    """Categorized, because the Tier 1 gazetteer reads this section hardest."""
    if not isinstance(skills, dict):
        return bullets(strings_of(skills))
    lines = []
    for category, entries in skills.items():
        if category in OMIT:
            continue
        # A bare string, or a dict of them, rather than the expected list.
        if isinstance(entries, str):
            entries = [entries]
        elif isinstance(entries, dict):
            entries = list(entries.values())
        names = []
        for e in entries or []:
            if isinstance(e, dict):
                if not e.get("name"):
                    continue
                # depth and recency are claims the profile makes, so an
                # uncurated dump keeps them. Parenthesised after the name so
                # the gazetteer still matches on the name itself.
                qual = [str(e[k]) for k in ("depth", "recency") if e.get(k)]
                names.append(("%s (%s)" % (e["name"], ", ".join(qual)))
                             if qual else str(e["name"]))
            elif e:
                names.append(str(e))
        if names:
            lines.append(r"\textbf{%s:} %s\par" % (
                tex_escape(category.replace("_", " ").title()),
                tex_escape(", ".join(names))))
    return lines


def render_entries(items, title_keys, sub_keys, date_keys):
    """One block per entry: a bold title line, a context line, its bullets."""
    lines = []
    # A dict here (keyed entries rather than a list) used to iterate its keys
    # and drop every value; a bare string used to iterate its characters.
    if isinstance(items, str):
        items = [items]
    elif isinstance(items, dict):
        items = list(items.values())
    for item in items or []:
        if not isinstance(item, dict):
            lines.extend(bullets([item]))
            continue
        shown = set()
        title = ""
        for k in title_keys:
            if item.get(k):
                title, _ = str(item[k]), shown.add(k)
                break
        sub = [str(item[k]) for k in sub_keys if item.get(k)]
        shown.update(k for k in sub_keys if item.get(k))
        if isinstance(item.get("stack"), list) and item["stack"]:
            sub.append(", ".join(str(s) for s in item["stack"]))
        date = ""
        for k in date_keys:
            if item.get(k):
                date, _ = str(item[k]), shown.add(k)
                break
        if item.get("start") or item.get("end"):
            date = "%s -- %s" % (item.get("start") or "",
                                 item.get("end") or "present")
        head = r"\textbf{%s}" % tex_escape(title) if title else ""
        if date:
            head += r"\hfill %s" % tex_escape(date)
        if head:
            lines += [head + r"\par"]
        if sub:
            lines += [r"\textit{%s}\par" % tex_escape(" | ".join(sub))]
        rows = []
        raw = item.get("bullets") or []
        # A bare string here used to be iterated character by character, so
        # a six-letter bullet became six bullets.
        if isinstance(raw, str):
            raw = [raw]
        elif isinstance(raw, dict):
            raw = list(raw.values())
        for b in raw:
            if isinstance(b, dict):
                text = b.get("text") or ""
                if b.get("metric"):
                    text = ("%s (%s)" % (text, b["metric"])).strip()
                rows.append(text)
            elif b:
                rows.append(str(b))
        lines += bullets(rows)
        # Anything else on the entry that is not already shown. `shown`
        # holds the keys actually rendered above, not every key that *could*
        # have been: an entry carrying both `title` and `role` renders one
        # as the heading, and the other belongs here rather than nowhere.
        extra = [v for k, v in item.items()
                 if k not in ("bullets", "stack", "start", "end")
                 and k not in shown and k not in OMIT
                 for v in strings_of(v)]
        lines += bullets(extra)
        lines += [r"\vspace{0.4em}"]
    return lines


def build_tex(profile):
    body = list(render_header(profile))
    body += section("Summary", bullets(strings_of(
        profile.get("summary_seeds"))))
    body += section("Skills", render_skills(profile.get("skills")))
    body += section("Experience", render_entries(
        profile.get("experience"), ("title", "role"),
        ("company", "organization", "location"), ("dates",)))
    body += section("Projects", render_entries(
        profile.get("projects"), ("name", "title"), ("url",), ("dates",)))
    body += section("Education", render_entries(
        profile.get("education"), ("degree",),
        ("institution", "field", "gpa"), ("graduation", "dates")))

    # Whatever else the profile carries -- publications, talks, awards,
    # funding, leadership, and the extensions profile-config.md allows.
    for key, value in profile.items():
        if key in EXPLICIT or key in OMIT or not value:
            continue
        rows = []
        for item in (value if isinstance(value, list) else [value]):
            joined = " | ".join(strings_of(item))
            if joined:
                rows.append(joined)
        body += section(key.replace("_", " "), bullets(rows))

    return PREAMBLE + "\n\\begin{document}\n" + "\n".join(body) + \
        "\n\\end{document}\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--profile",
                    default=os.path.join(ENGINE, "inputs", "profile.json"))
    ap.add_argument("--out",
                    default=os.path.join(ENGINE, "inputs",
                                         "profile-score.pdf"))
    ap.add_argument("--tectonic", default=os.path.join(ENGINE, "tectonic"),
                    help="compiler; defaults to the engine's own binary")
    ap.add_argument("--tex-only", action="store_true",
                    help="write the .tex beside --out and stop")
    a = ap.parse_args(argv)

    if not os.path.exists(a.profile):
        print(json.dumps({"ok": False,
                          "error": "no profile at %s -- run /ijob-profile"
                                   % a.profile}), file=sys.stderr)
        return 2
    with open(a.profile, encoding="utf-8") as fh:
        profile = json.load(fh)

    outdir = os.path.dirname(os.path.abspath(a.out)) or "."
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.out))[0]
    tex_path = os.path.join(outdir, stem + ".tex")
    with open(tex_path, "w", encoding="utf-8") as fh:
        fh.write(build_tex(profile))
    if a.tex_only:
        print(json.dumps({"ok": True, "tex": tex_path}))
        return 0

    if not os.path.exists(a.tectonic):
        print(json.dumps({"ok": False, "tex": tex_path,
                          "error": "no tectonic at %s -- run /ijob-setup"
                                   % a.tectonic}), file=sys.stderr)
        return 2

    # Remove the previous PDF before compiling. Left in place, a failed
    # rebuild leaves yesterday's profile on disk looking current, and
    # score_fit.py would happily score against it.
    stale_pdf = os.path.join(outdir, stem + ".pdf")
    if os.path.exists(stale_pdf):
        try:
            os.remove(stale_pdf)
        except OSError:
            pass
    # --keep-logs only so the page count can be read back; tectonic discards
    # the log otherwise, and the count is the one cheap sanity check there is.
    proc = subprocess.run([a.tectonic, "-X", "compile", tex_path,
                           "--outdir", outdir, "--keep-logs"],
                          capture_output=True, text=True)
    pdf = os.path.join(outdir, stem + ".pdf")
    if proc.returncode != 0 or not os.path.exists(pdf):
        print(json.dumps({"ok": False, "tex": tex_path,
                          "error": "compile failed",
                          "stderr": (proc.stderr or "")[-800:]}),
              file=sys.stderr)
        return 1
    pages = 0
    log = os.path.join(outdir, stem + ".log")
    if os.path.exists(log):
        with open(log, encoding="utf-8", errors="ignore") as fh:
            m = re.search(r"\((\d+) pages?", fh.read())
        pages = int(m.group(1)) if m else 0
        os.remove(log)
    print(json.dumps({"ok": True, "pdf": pdf, "pages": pages,
                      "bytes": os.path.getsize(pdf),
                      # Characters the font could not set, replaced by a
                      # space. Non-zero means the PDF is missing something
                      # the profile holds -- usually CJK, which Latin Modern
                      # cannot render at all.
                      "unrenderable_chars": DROPPED[0],
                      "profile_mtime": int(os.path.getmtime(a.profile))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
