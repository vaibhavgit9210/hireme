#!/usr/bin/env python3
"""Fetch jobs + competitions from free APIs into data/*.json for the hireme dashboard.

Zero external dependencies (stdlib only). Run by GitHub Actions daily, or locally:
    python3 scripts/refresh.py
Every source is free and keyless. A dead source logs a warning and is skipped.
"""
import json
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
UA = {"User-Agent": "Mozilla/5.0 (hireme dashboard; github.com/vaibhavgit9210/hireme)"}
NOW = datetime.now(timezone.utc)


def get(url, timeout=25, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if attempt == retries:
                print(f"  WARN {url.split('?')[0]}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))


def get_json(url, **kw):
    body = get(url, **kw)
    if body is None:
        return None
    try:
        return json.loads(body)
    except ValueError:
        print(f"  WARN not JSON: {url.split('?')[0]}", file=sys.stderr)
        return None


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, d):
        self.parts.append(d)


def strip_html(s):
    if not s:
        return ""
    p = TextExtractor()
    try:
        p.feed(s)
        return re.sub(r"\s+", " ", " ".join(p.parts)).strip()
    except Exception:
        return re.sub(r"<[^>]+>", " ", s)


def norm(title, company, location, url, source, posted=None, salary=None, desc=None, tags=None):
    return {
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "").strip(),
        "url": url,
        "source": source,
        "posted_at": posted,
        "salary": salary,
        "desc": strip_html(desc or "")[:600],
        "tags": tags or [],
    }


# ---------------------------------------------------------------- aggregators

def fetch_remotive(keyword):
    d = get_json("https://remotive.com/api/remote-jobs?limit=50&search=" + urllib.parse.quote(keyword))
    for j in (d or {}).get("jobs", []):
        yield norm(j.get("title"), j.get("company_name"), j.get("candidate_required_location") or "Remote",
                   j.get("url"), "Remotive", j.get("publication_date"), j.get("salary") or None,
                   j.get("description"), [j.get("category", "")])


_CACHE = {}


def cached(key, fn):
    """Fetch-once cache: rate-limited sources are hit a single time per run."""
    if key not in _CACHE:
        _CACHE[key] = fn()
    return _CACHE[key]


def fetch_remoteok(keyword):
    # RemoteOK returns everything; filter locally. First element is metadata/legal.
    d = cached("remoteok", lambda: get_json("https://remoteok.com/api"))
    kw = keyword.lower()
    for j in (d or [])[1:]:
        if not isinstance(j, dict):
            continue
        blob = " ".join([j.get("position", ""), j.get("description", ""), " ".join(j.get("tags") or [])]).lower()
        if all(w in blob for w in kw.split()):
            sal = None
            if j.get("salary_min"):
                sal = f"${int(j['salary_min']/1000)}k–${int((j.get('salary_max') or j['salary_min'])/1000)}k"
            yield norm(j.get("position"), j.get("company"), j.get("location") or "Remote",
                       j.get("url") or ("https://remoteok.com" + j.get("slug", "")), "RemoteOK",
                       j.get("date"), sal, j.get("description"), j.get("tags") or [])


def fetch_arbeitnow(keyword):
    # x-ratelimit-limit is 5/min — fetch both pages exactly once per run.
    kw = keyword.lower()
    for page in (1, 2):
        d = cached(f"arbeitnow{page}", lambda p=page: get_json(f"https://www.arbeitnow.com/api/job-board-api?page={p}"))
        for j in (d or {}).get("data", []):
            blob = (j.get("title", "") + " " + j.get("description", "") + " " + " ".join(j.get("tags") or [])).lower()
            if all(w in blob for w in kw.split()):
                posted = None
                if j.get("created_at"):
                    posted = datetime.fromtimestamp(j["created_at"], tz=timezone.utc).isoformat()
                loc = j.get("location") or ""
                if j.get("remote"):
                    loc = (loc + " · Remote").strip(" ·")
                yield norm(j.get("title"), j.get("company_name"), loc, j.get("url"), "Arbeitnow",
                           posted, None, j.get("description"), j.get("tags") or [])


def fetch_jobicy(keyword):
    d = get_json("https://jobicy.com/api/v2/remote-jobs?count=50&tag=" + urllib.parse.quote(keyword))
    for j in (d or {}).get("jobs", []):
        sal = None
        if j.get("annualSalaryMin"):
            sal = f"{j.get('salaryCurrency','USD')} {int(j['annualSalaryMin']/1000)}k–{int((j.get('annualSalaryMax') or j['annualSalaryMin'])/1000)}k"
        yield norm(j.get("jobTitle"), j.get("companyName"), j.get("jobGeo") or "Remote",
                   j.get("url"), "Jobicy", j.get("pubDate"), sal, j.get("jobExcerpt"),
                   j.get("jobIndustry") or [])


def fetch_himalayas(keyword):
    # No CORS headers, so this source is server-side only (not in the page's live search).
    d = cached("himalayas", lambda: get_json("https://himalayas.app/jobs/api?limit=100"))
    kw = keyword.lower()
    for j in (d or {}).get("jobs", []):
        blob = (j.get("title", "") + " " + j.get("excerpt", "") + " " + " ".join(j.get("categories") or [])).lower()
        if all(w in blob for w in kw.split()):
            posted = None
            if j.get("pubDate"):
                posted = datetime.fromtimestamp(j["pubDate"], tz=timezone.utc).isoformat()
            sal = None
            if j.get("minSalary"):
                sal = f"{j.get('salaryCurrency','USD')} {int(j['minSalary']/1000)}k–{int((j.get('maxSalary') or j['minSalary'])/1000)}k"
            yield norm(j.get("title"), j.get("companyName"), ", ".join(j.get("locationRestrictions") or []) or "Remote",
                       j.get("applicationLink") or j.get("guid"), "Himalayas", posted, sal,
                       j.get("excerpt"), j.get("categories") or [])


def _hn_comments():
    d = get_json("https://hn.algolia.com/api/v1/search_by_date?query=%22who%20is%20hiring%22&tags=story,author_whoishiring&hitsPerPage=1")
    hits = (d or {}).get("hits", [])
    if not hits:
        return []
    story_id = hits[0]["objectID"]
    out = []
    for page in range(3):
        c = get_json(f"https://hn.algolia.com/api/v1/search?tags=comment,story_{story_id}&hitsPerPage=100&page={page}")
        out.extend((c or {}).get("hits", []))
    return out


def fetch_hn_whoishiring(keyword):
    """Latest 'Ask HN: Who is hiring?' thread comments matching the keyword."""
    kw = keyword.lower()
    seeker = re.compile(r"looking for .{0,50}(role|job|opportunit|position)|seeking .{0,40}(role|position|job)|open to work|my resume|^\s*(hi+|hello)?[,!\s]*i'?\s?a?m ", re.I)
    for h in cached("hn", _hn_comments):
        text = strip_html(h.get("comment_text") or "")
        if seeker.search(text[:200]):
            continue
        if all(w in text.lower() for w in kw.split()):
            first = text.split("|")[0].strip()[:60] or "HN post"
            yield norm(f"HN: {first}", "", "see post", f"https://news.ycombinator.com/item?id={h['objectID']}",
                       "HN Who's Hiring", h.get("created_at"), None, text)


# ------------------------------------------------------------------ ATS boards

def fetch_greenhouse(company):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{company['token']}/jobs")
    for j in (d or {}).get("jobs", []):
        yield norm(j.get("title"), company["name"], (j.get("location") or {}).get("name", ""),
                   j.get("absolute_url"), f"Greenhouse · {company['name']}", j.get("updated_at"))


def fetch_lever(company):
    d = get_json(f"https://api.lever.co/v0/postings/{company['token']}?mode=json")
    for j in d or []:
        posted = None
        if j.get("createdAt"):
            posted = datetime.fromtimestamp(j["createdAt"] / 1000, tz=timezone.utc).isoformat()
        cats = j.get("categories") or {}
        yield norm(j.get("text"), company["name"], cats.get("location") or "",
                   j.get("hostedUrl"), f"Lever · {company['name']}", posted,
                   None, None, [cats.get("team") or "", cats.get("commitment") or ""])


def fetch_ashby(company):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{company['token']}?includeCompensation=true")
    for j in (d or {}).get("jobs", []):
        sal = (j.get("compensation") or {}).get("compensationTierSummary")
        loc = j.get("location") or ""
        if j.get("isRemote"):
            loc = (loc + " · Remote").strip(" ·")
        yield norm(j.get("title"), company["name"], loc, j.get("jobUrl") or j.get("applyUrl"),
                   f"Ashby · {company['name']}", j.get("publishedAt"), sal, None,
                   [j.get("department") or "", j.get("team") or ""])


ATS_FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}


def ats_relevant(job):
    """ATS boards list ALL roles; keep only ones matching target-role vocabulary."""
    t = job["title"].lower()
    hits = CONFIG["scoring"]["title_keywords"]
    return any(k in t for k in hits)


# --------------------------------------------------------------------- scoring

def score_job(job):
    s = CONFIG["scoring"]
    score = 0
    t = job["title"].lower()
    blob = (t + " " + job["desc"] + " " + " ".join(str(x) for x in job["tags"])).lower()
    loc = job["location"].lower()
    for k, v in s["title_keywords"].items():
        if k in t:
            score += v
    for k, v in s["description_keywords"].items():
        if k in blob:
            score += v
    loc_hit = False
    for k, v in s["location_boosts"].items():
        if k in loc:
            score += v
            loc_hit = True
    if loc and not loc_hit and "see post" not in loc:
        score -= 25  # onsite somewhere that is neither India nor remote
    for k, v in s["negative_keywords"].items():
        if k in t:
            score += v
    if job.get("salary"):
        score += s["salary_present_boost"]
    if job.get("posted_at"):
        try:
            posted = datetime.fromisoformat(job["posted_at"].replace("Z", "+00:00"))
            age = (NOW - posted).days
            for days, boost in sorted(s["recency_boost_days"].items(), key=lambda x: int(x[0])):
                if age <= int(days):
                    score += boost
                    break
            if age > 45:
                score -= 15
        except (ValueError, TypeError):
            pass
    return score


def dedupe(jobs):
    seen, out = set(), []
    for j in jobs:
        key = j["url"] or (j["company"].lower() + "|" + j["title"].lower())
        k2 = (j["company"].lower().strip(), j["title"].lower().strip())
        if key in seen or (all(k2) and k2 in seen):
            continue
        seen.add(key)
        if all(k2):
            seen.add(k2)
        out.append(j)
    return out


# ----------------------------------------------------------------- competitions

def devpost_deadline(period):
    """'Jul 10 - Aug 17, 2026' -> 'Aug 17, 2026'; 'Sep 15 - 21, 2026' -> 'Sep 21, 2026'."""
    if not period or "-" not in period:
        return (period or "").strip()
    left, right = [p.strip() for p in period.rsplit("-", 1)]
    if right and right[0].isdigit():  # month elided on the right side
        m = re.match(r"([A-Za-z]+)", left)
        if m:
            right = m.group(1) + " " + right
    return right


def fetch_devpost():
    for page in (1, 2, 3):
        d = get_json(f"https://devpost.com/api/hackathons?page={page}&status[]=open")
        for h in (d or {}).get("hackathons", []):
            prize = strip_html(h.get("prize_amount") or "")
            themes = [t.get("name", "") for t in h.get("themes") or []]
            yield {
                "title": h.get("title"),
                "platform": "Devpost",
                "url": h.get("url"),
                "prize": prize,
                "deadline": devpost_deadline(h.get("submission_period_dates")),
                "domain": ", ".join(themes),
                "participants": h.get("registrations_count"),
                "location": h.get("displayed_location", {}).get("location", ""),
            }


def fetch_hackerearth():
    d = get_json("https://www.hackerearth.com/chrome-extension/events/")
    for e in (d or {}).get("response", []):
        if e.get("status") not in ("ONGOING", "UPCOMING"):
            continue
        yield {
            "title": e.get("title"), "platform": "HackerEarth", "url": e.get("url"),
            "prize": "see page", "deadline": e.get("end_date") or "",
            "domain": e.get("challenge_type") or "hackathon",
            "participants": None, "location": "Online",
        }


def fetch_unstop():
    d = get_json("https://unstop.com/api/public/opportunity/search-result?opportunity=hackathons&per_page=40&oppstatus=open")
    items = ((d or {}).get("data") or {})
    items = items.get("data", []) if isinstance(items, dict) else items
    for e in items or []:
        cash = sum(p.get("cash") or 0 for p in e.get("prizes") or [])
        if cash <= 0:
            continue  # college events with certificates only — skip
        end = ((e.get("regnRequirements") or {}).get("end_regn_dt") or "")[:10]
        yield {
            "title": e.get("title"), "platform": "Unstop",
            "url": e.get("seo_url") or ("https://unstop.com/" + (e.get("public_url") or "")),
            "prize": f"₹{cash:,.0f}", "deadline": end,
            "domain": ", ".join(f.get("name", "") if isinstance(f, dict) else str(f) for f in (e.get("filters") or [])[:4]) or "hackathon",
            "participants": e.get("registerCount"), "location": "India",
        }


def domain_relevant(comp):
    blob = ((comp.get("title") or "") + " " + (comp.get("domain") or "")).lower()
    return any(k in blob for k in CONFIG["competition_domains"])


def parse_prize_value(prize):
    """Rough USD value for sorting; '₹5,00,000'→6000, '$50,000'→50000."""
    if not prize:
        return 0
    m = re.findall(r"[\d,]+", prize.replace(",", ""))
    if not m:
        return 0
    val = max(int(x) for x in m if x.isdigit()) if any(x.isdigit() for x in m) else 0
    if "₹" in prize or "INR" in prize.upper():
        val = val // 85
    return val


# ------------------------------------------------------------------------ main

def main():
    keywords = CONFIG["search_keywords"]
    jobs = []

    print("== Aggregator APIs ==")
    for name, fn, per_kw in [("Remotive", fetch_remotive, True), ("RemoteOK", fetch_remoteok, True),
                             ("Arbeitnow", fetch_arbeitnow, True), ("Jobicy", fetch_jobicy, True),
                             ("Himalayas", fetch_himalayas, True), ("HN", fetch_hn_whoishiring, True)]:
        got = 0
        try:
            kws = keywords if per_kw else [""]
            for kw in kws:
                for j in fn(kw) or []:
                    jobs.append(j)
                    got += 1
        except Exception as e:
            print(f"  WARN {name} failed: {e}", file=sys.stderr)
        print(f"  {name}: {got}")

    print("== ATS boards ==")
    companies_file = ROOT / "companies.json"
    if companies_file.exists():
        companies = json.loads(companies_file.read_text())
        for c in companies:
            fn = ATS_FETCHERS.get(c["ats"])
            if not fn:
                continue
            got = 0
            try:
                for j in fn(c) or []:
                    if ats_relevant(j):
                        jobs.append(j)
                        got += 1
            except Exception as e:
                print(f"  WARN {c['name']} failed: {e}", file=sys.stderr)
            print(f"  {c['name']}: {got}")

    jobs = dedupe(jobs)
    for j in jobs:
        j["score"] = score_job(j)
    jobs = [j for j in jobs if j["score"] > 0]
    jobs.sort(key=lambda j: -j["score"])
    jobs = jobs[:400]

    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data/jobs.json").write_text(json.dumps({
        "fetched_at": NOW.isoformat(), "count": len(jobs), "jobs": jobs,
    }, indent=1, ensure_ascii=False))
    print(f"Wrote data/jobs.json: {len(jobs)} jobs")

    print("== Competitions ==")
    comps = []
    for name, fn in [("Devpost", fetch_devpost), ("HackerEarth", fetch_hackerearth), ("Unstop", fetch_unstop)]:
        got = 0
        try:
            for c in fn() or []:
                comps.append(c)
                got += 1
        except Exception as e:
            print(f"  WARN {name} failed: {e}", file=sys.stderr)
        print(f"  {name}: {got}")

    seed_file = ROOT / "data/competitions_seed.json"
    if seed_file.exists():
        comps.extend(json.loads(seed_file.read_text()))

    comps = [c for c in comps if domain_relevant(c)]
    seen, out = set(), []
    for c in comps:
        k = (c.get("url") or c.get("title", "")).lower()
        if k not in seen:
            seen.add(k)
            c["prize_value"] = parse_prize_value(c.get("prize", ""))
            out.append(c)
    out.sort(key=lambda c: -c["prize_value"])

    (ROOT / "data/competitions.json").write_text(json.dumps({
        "fetched_at": NOW.isoformat(), "count": len(out), "competitions": out,
    }, indent=1, ensure_ascii=False))
    print(f"Wrote data/competitions.json: {len(out)} competitions")


if __name__ == "__main__":
    main()
