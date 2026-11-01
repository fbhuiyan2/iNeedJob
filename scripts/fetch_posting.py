#!/usr/bin/env python3
"""Fetch a job posting from a URL and write it as plain text plus metadata.

Standard library only. No pip install, no browser, no API key.

    python3 -I fetch_posting.py URL [URL ...] --root DIR
    python3 -I fetch_posting.py URL --out DIR

--root DIR   writes each posting into DIR/{company-slug}_{role-slug}/
--out  DIR   writes a single posting into DIR exactly

Each posting directory gets:
    job-posting.txt   provenance header + the full posting text, verbatim
    jd.meta.json      {title, company, location, url, source, captured_at, ...}

A one-line-per-posting JSON summary goes to stdout (the posting text is NOT
included, so an agent can read the result without pulling the body into
context). Exit status is 0 if every URL succeeded, 1 if any failed.

Known boards are read through their public JSON APIs, which return the posting
as structured data rather than a rendered page. Anything else falls back to
JSON-LD (schema.org JobPosting, which most boards embed for Google indexing)
and then to tag stripping. A page that renders only under JavaScript cannot be
read this way; the summary says so via "needs_browser": true, and the caller
should retry with a fetch tool or ask the user to paste the text.
"""

import argparse
import datetime as _dt
import gzip
import html as _html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
TIMEOUT = 30


# --------------------------------------------------------------------------- 
# HTTP
# ---------------------------------------------------------------------------

def http(url, data=None, headers=None, timeout=TIMEOUT):
    """GET (or POST when data is given) and return (text, final_url)."""
    hdrs = {
        "User-Agent": UA,
        "Accept": "text/html,application/json,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }
    if headers:
        hdrs.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = (r.headers.get("Content-Encoding") or "").lower()
        final = r.geturl()
    if enc == "gzip":
        raw = gzip.decompress(raw)
    elif enc == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw.decode("utf-8", "replace"), final


def http_json(url, data=None, headers=None):
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    text, _ = http(url, data=data, headers=hdrs)
    return json.loads(text)


# ---------------------------------------------------------------------------
# HTML -> text
# ---------------------------------------------------------------------------

def html_to_text(frag):
    """Flatten an HTML fragment to readable text, keeping list and block breaks."""
    if not frag:
        return ""
    s = frag
    # Some sources return HTML that is itself entity-encoded (Greenhouse's
    # `content`, and many JSON-LD `description` fields). A posting can mix the
    # two, so test for encoded TAGS rather than for the absence of real ones.
    if re.search(r"&lt;/?[a-zA-Z]", s):
        s = _html.unescape(s)
    s = re.sub(r"(?is)<(script|style|noscript|svg|head|nav|footer)\b.*?</\1>", " ", s)
    s = re.sub(r"(?is)<!--.*?-->", " ", s)
    s = re.sub(r"(?i)<li\b[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)<(br|hr)\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|ul|ol|section|article|table)\s*>", "\n", s)
    s = re.sub(r"(?i)<(p|div|h[1-6]|section|article|tr)\b[^>]*>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = _html.unescape(s)
    s = s.replace(" ", " ").replace("​", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = "\n".join(line.strip() for line in s.splitlines())
    # A <li> wrapping a block element leaves the marker stranded on its own
    # line; rejoin it with the text it belongs to.
    s = re.sub(r"(?m)^-[ \t]*\n+[ \t]*", "- ", s)
    # Keep list items adjacent so a requirements list reads as one block.
    s = re.sub(r"(?m)^(- .*)\n\n+(?=- )", r"\1\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def slug(value, limit=60):
    s = (value or "").lower()
    s = s.encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > limit:
        cut = s[:limit]
        # Prefer the last whole word over a truncated one, unless that leaves
        # almost nothing (a single very long token).
        if "-" in cut and cut.rindex("-") >= limit // 2:
            cut = cut[:cut.rindex("-")]
        s = cut
    return s.strip("-") or "unknown"


def titlecase_token(tok):
    """Turn an ATS account token (acme-corp, acmeCorp) into something readable."""
    s = re.sub(r"[-_]+", " ", tok or "").strip()
    if s and s == s.lower():
        s = " ".join(w.capitalize() for w in s.split())
    return s


# ---------------------------------------------------------------------------
# Board handlers.  Each returns a posting dict or raises.
# ---------------------------------------------------------------------------

def _posting(**kw):
    p = {"title": "", "company": "", "location": "", "url": "", "source": "",
         "posted_on": "", "apply_url": "", "req_id": "", "employment_type": "",
         "compensation": "", "department": "", "text": ""}
    p.update({k: v for k, v in kw.items() if v})
    return p


def grab_greenhouse(url, u):
    m = re.search(r"/(?:embed/job_app\?for=|)([A-Za-z0-9_.-]+)/jobs/(\d+)", u.path) \
        or re.search(r"[?&]for=([A-Za-z0-9_.-]+)", u.query)
    board = job_id = None
    if m and m.lastindex == 2:
        board, job_id = m.group(1), m.group(2)
    else:
        qs = urllib.parse.parse_qs(u.query)
        board = (qs.get("for") or [None])[0]
        if not board:
            # job-boards.greenhouse.io/{board}?gh_jid=123 — board in the path,
            # id in a bare query param, no for=. CMS integrations emit this.
            segs = [p for p in u.path.split("/") if p and p != "embed"]
            if segs:
                board = segs[0]
        jm = re.search(r"(?:gh_jid=|/jobs/)(\d+)", url)
        job_id = jm.group(1) if jm else None
    if not (board and job_id):
        raise ValueError("could not read greenhouse board/job id from URL")
    d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}")
    loc = (d.get("location") or {}).get("name", "")
    offices = ", ".join(o.get("name", "") for o in (d.get("offices") or []) if o.get("name"))
    depts = ", ".join(x.get("name", "") for x in (d.get("departments") or []) if x.get("name"))
    return _posting(
        title=d.get("title", ""),
        company=d.get("company_name") or titlecase_token(board),
        location=loc or offices,
        url=d.get("absolute_url") or url,
        source="greenhouse",
        posted_on=(d.get("first_published") or d.get("updated_at") or "")[:10],
        req_id=str(d.get("requisition_id") or ""),
        department=depts,
        text=html_to_text(d.get("content", "")),
    )


def grab_lever(url, u):
    parts = [p for p in u.path.split("/") if p]
    if len(parts) < 2:
        raise ValueError("could not read lever company/posting id from URL")
    company, job_id = parts[0], parts[1]
    d = http_json(f"https://api.lever.co/v0/postings/{company}/{job_id}")
    cats = d.get("categories") or {}
    chunks = []
    if d.get("descriptionPlain"):
        chunks.append(d["descriptionPlain"])
    for lst in d.get("lists") or []:
        head = html_to_text(lst.get("text", ""))
        body = html_to_text(lst.get("content", ""))
        chunks.append((head + "\n" + body).strip())
    if d.get("additionalPlain"):
        chunks.append(d["additionalPlain"])
    posted = d.get("createdAt")
    if isinstance(posted, (int, float)):
        posted = _dt.datetime.fromtimestamp(
            posted / 1000, _dt.timezone.utc).date().isoformat()
    locs = cats.get("allLocations") or ([cats["location"]] if cats.get("location") else [])
    return _posting(
        title=d.get("text", ""),
        company=titlecase_token(company),
        location=", ".join(locs),
        url=d.get("hostedUrl") or url,
        source="lever",
        posted_on=posted or "",
        apply_url=d.get("applyUrl", ""),
        employment_type=cats.get("commitment", ""),
        department=cats.get("department") or cats.get("team") or "",
        text="\n\n".join(c for c in chunks if c),
    )


def grab_ashby(url, u):
    parts = [p for p in u.path.split("/") if p]
    if not parts:
        raise ValueError("could not read ashby org from URL")
    org = parts[0]
    job_id = parts[1] if len(parts) > 1 else None
    d = http_json(
        f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true")
    jobs = d.get("jobs") or []
    job = None
    if job_id:
        job = next((j for j in jobs if j.get("id") == job_id), None)
        if job is None:
            job = next((j for j in jobs if job_id in (j.get("jobUrl") or "")), None)
    if job is None:
        raise ValueError(f"posting {job_id} not on the {org} Ashby board")
    comp = job.get("compensation") or {}
    summary = comp.get("compensationTierSummary") if isinstance(comp, dict) else ""
    return _posting(
        title=(job.get("title") or "").strip(),
        company=titlecase_token(org),
        location=job.get("location", ""),
        url=job.get("jobUrl") or url,
        source="ashby",
        posted_on=(job.get("publishedAt") or "")[:10],
        apply_url=job.get("applyUrl", ""),
        employment_type=job.get("employmentType", ""),
        compensation=summary or "",
        department=job.get("department") or job.get("team") or "",
        text=job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml", "")),
    )


LEGAL_SUFFIX = re.compile(
    r"(?i)[\s,]+(company limited|co\.?,? ?ltd\.?|ltd\.?|llc|l\.l\.c\.|inc\.?|"
    r"incorporated|corp\.?|corporation|gmbh|s\.?a\.?r\.?l\.?|b\.?v\.?|"
    r"pty\.? ?ltd\.?|plc|ag|nv|sas?|s\.?p\.?a\.?|k\.?k\.?|pvt\.? ?ltd\.?)$")


def clean_org(name):
    """Trim a Workday legal-entity name back to something a letter can address.

    Workday returns the hiring legal entity, which is often prefixed with a
    site code and suffixed with an incorporation form: "VN01 NVIDIA Vietnam
    Company Limited". Neither belongs in "Dear <Company> Hiring Team".
    """
    s = (name or "").strip()
    s = re.sub(r"^[A-Z]{2,4}\d{2,4}\s+", "", s)
    for _ in range(3):
        new = LEGAL_SUFFIX.sub("", s).strip(" ,.-")
        if new == s:
            break
        s = new
    return s.strip()


def grab_workday(url, u):
    # https://{tenant}.{wdN}.myworkdayjobs.com[/{lang}]/{site}/job/{loc}/{title}_{req}
    host = u.netloc
    tenant = host.split(".")[0]
    parts = [p for p in u.path.split("/") if p]
    if "job" not in parts:
        raise ValueError("not a Workday job-detail URL (no /job/ segment)")
    ji = parts.index("job")
    if ji == 0:
        raise ValueError("could not read Workday site id from URL")
    site = parts[ji - 1]
    tail = "/".join(parts[ji:])
    api = f"https://{host}/wday/cxs/{tenant}/{site}/{tail}"
    d = http_json(api)
    info = d.get("jobPostingInfo") or {}
    org = clean_org((d.get("hiringOrganization") or {}).get("name")) \
        or titlecase_token(tenant)
    return _posting(
        title=info.get("title", ""),
        company=org,
        location=", ".join(
            x for x in [info.get("location", "")] + list(info.get("additionalLocations") or []) if x),
        url=info.get("externalUrl") or url,
        source="workday",
        posted_on=info.get("startDate", "") or info.get("postedOn", ""),
        req_id=info.get("jobReqId", ""),
        employment_type=info.get("timeType", ""),
        text=html_to_text(info.get("jobDescription", "")),
    )


def grab_smartrecruiters(url, u):
    m = re.search(r"/([^/]+)/(\d+)", u.path)
    if not m:
        raise ValueError("could not read SmartRecruiters company/posting id from URL")
    company, job_id = m.group(1), m.group(2)
    d = http_json(
        f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{job_id}")
    sections = ((d.get("jobAd") or {}).get("sections") or {})
    order = ["companyDescription", "jobDescription", "qualifications",
             "additionalInformation"]
    chunks = []
    for key in order + [k for k in sections if k not in order]:
        sec = sections.get(key) or {}
        body = html_to_text(sec.get("text", ""))
        if body:
            chunks.append(((sec.get("title") or "").strip() + "\n" + body).strip())
    loc = d.get("location") or {}
    return _posting(
        title=d.get("name", ""),
        company=(d.get("company") or {}).get("name") or titlecase_token(company),
        location=loc.get("fullLocation") or ", ".join(
            x for x in [loc.get("city"), loc.get("country")] if x),
        url=d.get("postingUrl") or url,
        source="smartrecruiters",
        posted_on=(d.get("releasedDate") or "")[:10],
        apply_url=d.get("applyUrl", ""),
        req_id=d.get("refNumber", ""),
        employment_type=(d.get("typeOfEmployment") or {}).get("label", ""),
        department=(d.get("function") or {}).get("label", ""),
        text="\n\n".join(chunks),
    )


def grab_recruitee(url, u):
    company = u.netloc.split(".")[0]
    parts = [p for p in u.path.split("/") if p]
    want = parts[-1] if parts else ""
    d = http_json(f"https://{company}.recruitee.com/api/offers/")
    offers = d.get("offers") or []
    job = next((o for o in offers if o.get("slug") == want), None)
    if job is None:
        job = next((o for o in offers if want and want in str(o.get("id"))), None)
    if job is None:
        raise ValueError(f"posting {want} not on the {company} Recruitee board")
    body = "\n\n".join(
        html_to_text(job.get(k, "")) for k in ("description", "requirements") if job.get(k))
    return _posting(
        title=job.get("title", ""),
        company=job.get("company_name") or titlecase_token(company),
        location=job.get("location") or job.get("city", ""),
        url=job.get("careers_url") or url,
        source="recruitee",
        posted_on=(job.get("published_at") or "")[:10],
        employment_type=job.get("employment_type_code", ""),
        department=job.get("department", ""),
        text=body,
    )


# --- generic -----------------------------------------------------------------

def _first(x):
    if isinstance(x, list):
        return x[0] if x else None
    return x


def _org_name(org):
    org = _first(org)
    if isinstance(org, dict):
        return org.get("name", "")
    return org or ""


def _loc_name(loc):
    out = []
    for item in (loc if isinstance(loc, list) else [loc]):
        if not isinstance(item, dict):
            if item:
                out.append(str(item))
            continue
        addr = item.get("address")
        if isinstance(addr, dict):
            bits = [addr.get("addressLocality"), addr.get("addressRegion"),
                    addr.get("addressCountry")]
            bits = [b.get("name") if isinstance(b, dict) else b for b in bits]
            out.append(", ".join(str(b) for b in bits if b))
        elif item.get("name"):
            out.append(item["name"])
    return " | ".join(x for x in out if x)


def iter_jsonld(page):
    for m in re.finditer(
            r"(?is)<script[^>]+type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
            page):
        blob = m.group(1).strip()
        try:
            data = json.loads(blob)
        except Exception:
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", blob))
            except Exception:
                continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                types = node.get("@type")
                types = types if isinstance(types, list) else [types]
                if "JobPosting" in [t for t in types if t]:
                    yield node
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))


def grab_generic(url, u):
    page, final = http(url)
    check_not_redirected(url, final)
    for node in iter_jsonld(page):
        text = html_to_text(node.get("description", ""))
        if len(text) < 200:
            continue
        salary = ""
        bs = node.get("baseSalary")
        if isinstance(bs, dict):
            val = bs.get("value")
            if isinstance(val, dict):
                lo, hi = val.get("minValue"), val.get("maxValue")
                unit = val.get("unitText", "")
                salary = " - ".join(str(x) for x in [lo, hi] if x is not None)
                if salary and unit:
                    salary += f" per {unit.lower()}"
        return _posting(
            title=node.get("title", ""),
            company=_org_name(node.get("hiringOrganization")),
            location=_loc_name(node.get("jobLocation")) or (
                "Remote" if node.get("jobLocationType") == "TELECOMMUTE" else ""),
            url=node.get("url") or final,
            source="jsonld",
            posted_on=(node.get("datePosted") or "")[:10],
            employment_type=str(_first(node.get("employmentType")) or ""),
            compensation=salary,
            req_id=str(node.get("identifier", {}).get("value", "")
                       if isinstance(node.get("identifier"), dict) else ""),
            text=text,
        )

    body = html_to_text(page)
    tm = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    title = _html.unescape(tm.group(1)).strip() if tm else ""
    om = re.search(r"(?is)<meta[^>]+property=[\"']og:site_name[\"'][^>]+content=[\"']([^\"']+)",
                   page)
    company = _html.unescape(om.group(1)).strip() if om else ""
    if not company:
        host = urllib.parse.urlparse(final).netloc
        company = titlecase_token(re.sub(r"^(www|jobs|careers|apply)\.", "", host).split(".")[0])
    # A JS-only page returns a shell: a little chrome text and nothing else.
    if len(body) < 600:
        raise BrowserNeeded(
            f"page returned {len(body)} characters of text, so it is rendered "
            f"client-side and cannot be read without a browser")
    return _posting(title=title, company=company, url=final, source="html-fallback",
                    text=body)


class BrowserNeeded(Exception):
    pass


class PostingGone(Exception):
    """The server sent us somewhere other than the posting we asked for."""


def posting_id_token(url):
    """The id in a posting URL, if it carries a recognisable one."""
    u = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(u.query)
    for key in ("gh_jid", "jobId", "job_id", "jobid", "id", "reqid"):
        for v in qs.get(key) or []:
            if re.fullmatch(r"\d{3,}|[0-9a-fA-F-]{36}", v):
                return v
    for seg in reversed([p for p in u.path.split("/") if p]):
        m = re.search(
            r"(\d{4,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            seg, re.I)
        if m:
            return m.group(1)
    return None


def check_not_redirected(requested, final):
    """Raise if the server bounced us off the posting onto something else.

    A posting that has closed often 30x-redirects to the board's landing page
    rather than returning 404. The HTML there parses perfectly well, so without
    this check the fetch reports ok and hands back the company's careers blurb
    in place of the job — which then gets tailored against, silently.
    """
    if requested == final:
        return
    token = posting_id_token(requested)
    if token and token not in final:
        raise PostingGone(
            f"requested posting {token} but was redirected to {final}; the "
            f"posting has most likely closed")
    rp = [p for p in urllib.parse.urlparse(requested).path.split("/") if p]
    fp = [p for p in urllib.parse.urlparse(final).path.split("/") if p]
    if len(fp) < len(rp) and rp[:len(fp)] == fp:
        raise PostingGone(
            f"redirected from the posting up to {final}, which is a listing "
            f"page, not a job; the posting has most likely closed")


HANDLERS = [
    (r"(^|\.)(boards|job-boards|boards-api)\.greenhouse\.io$", grab_greenhouse),
    (r"(^|\.)greenhouse\.io$", grab_greenhouse),
    (r"(^|\.)lever\.co$", grab_lever),
    (r"(^|\.)ashbyhq\.com$", grab_ashby),
    (r"\.myworkdayjobs\.com$", grab_workday),
    (r"(^|\.)smartrecruiters\.com$", grab_smartrecruiters),
    (r"(^|\.)recruitee\.com$", grab_recruitee),
]

UNREADABLE = {
    "linkedin.com": "LinkedIn blocks non-browser requests and requires a login",
    "indeed.com": "Indeed serves a bot challenge to non-browser requests",
    "glassdoor.com": "Glassdoor serves a bot challenge to non-browser requests",
    "ziprecruiter.com": "ZipRecruiter serves a bot challenge to non-browser requests",
}


def fetch_posting(url):
    u = urllib.parse.urlparse(url)
    host = u.netloc.lower().split("@")[-1].split(":")[0]
    for pat, fn in HANDLERS:
        if re.search(pat, host):
            return fn(url, u)
    for bad, why in UNREADABLE.items():
        if host == bad or host.endswith("." + bad):
            raise BrowserNeeded(why)
    return grab_generic(url, u)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def render(p):
    head = [f"Title: {p['title']}"]
    for label, key in (("Company", "company"), ("Location", "location"),
                       ("Employment type", "employment_type"),
                       ("Department", "department"), ("Compensation", "compensation"),
                       ("Requisition", "req_id"), ("Posted", "posted_on"),
                       ("URL", "url")):
        if p.get(key):
            head.append(f"{label}: {p[key]}")
    return "\n".join(head) + "\n\n" + p["text"] + "\n"


def target_dir(p, root, out, on_exist):
    if out:
        # --out names the directory, so there is nothing to suffix. "skip"
        # still has to be honoured though: it is what lets an interrupted
        # batch resume without re-fetching, and silently ignoring it here
        # made every resumed job download again.
        if on_exist == "skip" and os.path.exists(
                os.path.join(out, "job-posting.txt")):
            return out, True
        os.makedirs(out, exist_ok=True)
        return out, False
    name = f"{slug(p['company'], 40)}_{slug(p['title'], 40)}"
    base = os.path.join(root, name)
    path = base
    if os.path.exists(os.path.join(path, "job-posting.txt")):
        if on_exist == "skip":
            return path, True
        if on_exist == "suffix":
            n = 2
            while os.path.exists(os.path.join(f"{base}-{n}", "job-posting.txt")):
                n += 1
            path = f"{base}-{n}"
    os.makedirs(path, exist_ok=True)
    return path, False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("urls", nargs="+")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--root", help="create DIR/{company}_{role}/ per posting")
    g.add_argument("--out", help="write one posting into DIR exactly")
    ap.add_argument("--on-exist", choices=["suffix", "skip", "replace"], default="suffix",
                    help="what to do when the posting directory already has a posting")
    ap.add_argument("--min-chars", type=int, default=400,
                    help="flag a posting shorter than this as suspect (default 400)")
    args = ap.parse_args(argv)

    if args.out and len(args.urls) > 1:
        ap.error("--out takes a single URL; use --root for several")

    now = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    results, failed = [], 0

    for url in args.urls:
        rec = {"url": url, "ok": False}
        try:
            p = fetch_posting(url)
            if not p["text"].strip():
                raise BrowserNeeded("the posting body came back empty")
            d, skipped = target_dir(p, args.root, args.out, args.on_exist)
            rec.update(dir=d, source=p["source"], title=p["title"],
                       company=p["company"], location=p["location"],
                       posted_on=p["posted_on"], chars=len(p["text"]), ok=True)
            if skipped:
                rec["skipped"] = "directory already holds a posting"
            else:
                meta = {"title": p["title"], "company": p["company"],
                        "location": p["location"], "url": p["url"] or url,
                        "source": p["source"], "captured_at": now,
                        "requested_url": url}
                for k in ("posted_on", "apply_url", "req_id", "employment_type",
                          "compensation", "department"):
                    if p.get(k):
                        meta[k] = p[k]
                with open(os.path.join(d, "job-posting.txt"), "w", encoding="utf-8") as f:
                    f.write(render(p))
                with open(os.path.join(d, "jd.meta.json"), "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)
                    f.write("\n")
            warn = []
            if len(p["text"]) < args.min_chars:
                warn.append(f"only {len(p['text'])} characters of body text; "
                            f"check job-posting.txt before tailoring")
            if not p["title"]:
                warn.append("no title found")
            if not p["company"]:
                warn.append("no company found")
            if p["source"] == "html-fallback":
                warn.append("read by stripping page HTML, so navigation and footer "
                            "text may be mixed in")
            if warn:
                rec["warnings"] = warn
        except PostingGone as e:
            rec.update(error=str(e), posting_gone=True)
            failed += 1
        except BrowserNeeded as e:
            rec.update(error=str(e), needs_browser=True)
            failed += 1
        except urllib.error.HTTPError as e:
            rec.update(error=f"HTTP {e.code} {e.reason}",
                       needs_browser=e.code in (401, 403, 429))
            failed += 1
        except Exception as e:
            rec.update(error=f"{type(e).__name__}: {e}")
            failed += 1
        results.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
