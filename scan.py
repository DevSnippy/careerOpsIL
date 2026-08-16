#!/usr/bin/env python3
"""scan: fetch new job postings for tracked companies and add them to the
pipeline.

Greenhouse and Ashby providers are live-tested and confirmed; Lever is
implemented from its public API shape but not verified against real
posting data. Other ATS provider types are out of scope for now.

run_scan() is also imported directly by dashboard.py's "S" scan-results
screen so the TUI can show what was found without going through a
subprocess.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from urllib.parse import urlparse

import yaml

SCAN_HISTORY_HEADER = ("url\tfirst_seen\tportal\ttitle\tcompany\tstatus\tlocation\t"
                        "fingerprint\tposted_at\ttrust_score\ttrust_flags\tnormalized_company")
SCAN_RUNS_HEADER = ("timestamp\tstatus\tcompanies\tboards\tfound\tfiltered_title\t"
                     "filtered_tier\tfiltered_location\tfiltered_posting_age\t"
                     "filtered_salary\tfiltered_content\tfiltered_cooldown\tdupes\t"
                     "new_added\terrors\tfiltered_blacklist\tfiltered_visa\t"
                     "filtered_posted_date\tfiltered_country_eligibility")
PORTAL_HEALTH_HEADER = "timestamp\tcompany\tstatus"

PIPELINE_HEADER = (
    "# Pipeline — Pending URLs\n\n"
    "Paste job URLs below as `- [ ] {url}` then run `/careeropsil pipeline`.\n\n"
    "## Pending\n\n"
)


def fetch_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "careeropsil-scan/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def detect_provider(careers_url):
    host = urlparse(careers_url).netloc
    path = urlparse(careers_url).path.strip("/")
    if host == "job-boards.greenhouse.io" and path:
        return "greenhouse", path
    if host == "jobs.ashbyhq.com" and path:
        return "ashby", path
    if host == "jobs.lever.co" and path:
        return "lever", path
    return None, None


def fetch_greenhouse(slug):
    data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false")
    postings = []
    for job in data.get("jobs", []):
        postings.append({
            "url": job["absolute_url"],
            "title": job["title"],
            "location": (job.get("location") or {}).get("name", ""),
            "posted_at": (job.get("first_published") or "")[:10],
        })
    return postings


def fetch_ashby(slug):
    data = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    postings = []
    for job in data.get("jobs", []):
        postings.append({
            "url": job["jobUrl"],
            "title": job["title"],
            "location": job.get("location", ""),
            "posted_at": (job.get("publishedAt") or "")[:10],
        })
    return postings


def fetch_lever(slug):
    # Public API shape confirmed (empty-array response verified live); real
    # posting data not verified this round — see spec §1.
    data = fetch_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    postings = []
    for job in data if isinstance(data, list) else []:
        postings.append({
            "url": job.get("hostedUrl", ""),
            "title": job.get("text", ""),
            "location": (job.get("categories") or {}).get("location", ""),
            "posted_at": "",
        })
    return postings


PROVIDERS = {"greenhouse": fetch_greenhouse, "ashby": fetch_ashby, "lever": fetch_lever}
PROVIDER_TAG = {"greenhouse": "greenhouse-api", "ashby": "ashby-api", "lever": "lever-api"}

SHORT_WORD_RE_CACHE = {}


def jobspy_available():
    try:
        import jobspy  # noqa: F401
        return True
    except ImportError:
        return False


def fetch_jobspy(search_term, sites, results_wanted=20, country_indeed="usa", location=""):
    """Broad multi-board search via the jobspy library (MIT-licensed,
    github.com/Bunsly/JobSpy — a separate dependency, requires Python
    >=3.10). NOT a port of anything — this is new functionality, added
    because the underlying library already exists and is meant to be used
    this way, not because any other project's code was copied.

    country_indeed scopes which Indeed country site is queried (jobspy's
    Country enum, e.g. "usa", "israel", "uk" — lowercase country name);
    location is a free-text search-location hint passed to all sites.
    Without both, every search defaults to US-scoped results regardless
    of any location_filter applied afterward — confirmed by testing:
    location_filter can only narrow down what was fetched, it can't widen
    a search that was never scoped to the right country in the first place."""
    import jobspy

    def clean_str(value, default=""):
        # pandas represents missing string cells as float('nan'), which is
        # truthy in Python — `value or default` alone doesn't catch it.
        try:
            if value is None or (isinstance(value, float) and value != value):
                return default
        except Exception:
            pass
        text = str(value).strip()
        return text if text and text.lower() != "nan" else default

    postings = []
    # One scrape_jobs() call per site rather than passing the whole list at
    # once: confirmed some (site, country) combinations aren't supported at
    # all (e.g. Glassdoor has no Israel presence — jobspy raises internally),
    # and when jobspy scrapes several sites in one call via its own thread
    # pool, one site's exception kills the whole batch, silently zeroing out
    # every OTHER site's results too. Per-site isolation means a bad
    # combination only drops that one site, not the entire search.
    for site in sites:
        kwargs = {"site_name": [site], "search_term": search_term,
                  "results_wanted": results_wanted, "country_indeed": country_indeed}
        if location:
            kwargs["location"] = location
        try:
            df = jobspy.scrape_jobs(**kwargs)
        except Exception:
            continue
        for _, row in df.iterrows():
            posted_str = clean_str(row.get("date_posted"))
            if posted_str == "NaT":
                posted_str = ""
            postings.append({
                "url": clean_str(row.get("job_url")),
                "title": clean_str(row.get("title")),
                "company": clean_str(row.get("company"), "?"),
                "location": clean_str(row.get("location")),
                "posted_at": posted_str,
                "site": clean_str(row.get("site"), site),
            })
    return postings


def title_matches(title, keywords):
    title_lower = title.lower()
    for kw in keywords:
        if " + " in kw:
            terms = [t.strip().lower() for t in kw.split(" + ")]
            if all(t in title_lower for t in terms):
                return True
            continue
        kw_lower = kw.lower()
        if len(kw) <= 3 and kw.isalpha():
            pattern = SHORT_WORD_RE_CACHE.setdefault(
                kw_lower, re.compile(r"\b" + re.escape(kw_lower) + r"\b")
            )
            if pattern.search(title_lower):
                return True
        elif kw_lower in title_lower:
            return True
    return False


def location_allowed(location, location_filter):
    if not location_filter:
        return True
    if not location.strip():
        return True
    loc_lower = location.lower()
    always_allow = location_filter.get("always_allow") or []
    block = location_filter.get("block") or []
    allow = location_filter.get("allow") or []
    if any(kw.lower() in loc_lower for kw in always_allow):
        return True
    if any(kw.lower() in loc_lower for kw in block):
        return False
    if not allow:
        return True
    return any(kw.lower() in loc_lower for kw in allow)


def normalize_company(name):
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def load_scan_history_urls(scan_history_path):
    if not os.path.exists(scan_history_path):
        return set()
    with open(scan_history_path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    urls = set()
    for line in lines[1:]:
        parts = line.split("\t")
        if parts:
            urls.add(parts[0])
    return urls


def append_tsv(path, header, row):
    is_new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        if is_new:
            f.write(header + "\n")
        f.write("\t".join(str(x) for x in row) + "\n")


def append_pipeline_entries(pipeline_path, entries):
    if not os.path.exists(pipeline_path):
        os.makedirs(os.path.dirname(pipeline_path) or ".", exist_ok=True)
        with open(pipeline_path, "w", encoding="utf-8") as f:
            f.write(PIPELINE_HEADER)
    with open(pipeline_path, "a", encoding="utf-8") as f:
        for e in entries:
            line = f"- [ ] {e['url']} | {e['company']} | {e['title']} | {e['location']}"
            if e["posted_at"]:
                line += f" | posted: {e['posted_at']}"
            f.write(line + "\n")


PENDING_LINE_RE = re.compile(
    r"^-\s*\[ \]\s*(?P<url>\S+)\s*\|\s*(?P<company>[^|]*)\|\s*(?P<title>[^|]*)"
    r"\|\s*(?P<location>[^|]*?)(?:\s*\|\s*posted:\s*(?P<posted>\S+))?$"
)


def load_pending_pipeline(base_path="."):
    """Parses data/pipeline.md's pending checklist back into entry dicts —
    this is what makes a scanned list persistent and reopenable across
    sessions, rather than living only in the TUI's in-memory state for as
    long as that one screen stays open."""
    pipeline_path = os.path.join(base_path, "data", "pipeline.md")
    if not os.path.exists(pipeline_path):
        return []
    entries = []
    with open(pipeline_path, encoding="utf-8") as f:
        for line in f:
            m = PENDING_LINE_RE.match(line.strip())
            if not m:
                continue
            entries.append({
                "url": m.group("url"), "company": m.group("company").strip(),
                "title": m.group("title").strip(), "location": m.group("location").strip(),
                "posted_at": m.group("posted") or "",
            })
    return entries


def remove_pipeline_entry(base_path, url):
    """Removes one entry (matched by URL) from data/pipeline.md — used
    when a pending entry gets discarded, added, or evaluated, so it
    doesn't keep reappearing in the persisted pending list."""
    pipeline_path = os.path.join(base_path, "data", "pipeline.md")
    if not os.path.exists(pipeline_path):
        return
    with open(pipeline_path, encoding="utf-8") as f:
        lines = f.readlines()
    lines = [ln for ln in lines if url not in ln]
    with open(pipeline_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def run_scan(base_path="."):
    """Runs a full scan and writes results to base_path's data/ files.
    Returns a result dict; raises FileNotFoundError if portals.yml is missing."""
    portals_path = os.path.join(base_path, "portals.yml")
    pipeline_path = os.path.join(base_path, "data", "pipeline.md")
    scan_history_path = os.path.join(base_path, "data", "scan-history.tsv")
    scan_runs_path = os.path.join(base_path, "data", "scan-runs.tsv")
    portal_health_path = os.path.join(base_path, "data", "portal-health.tsv")

    if not os.path.exists(portals_path):
        raise FileNotFoundError(portals_path)

    with open(portals_path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    title_filter = config.get("title_filter") or {}
    positive = title_filter.get("positive") or []
    negative = title_filter.get("negative") or []
    location_filter = config.get("location_filter") or {}
    companies = [c for c in (config.get("tracked_companies") or [])
                 if c.get("enabled", True)]

    seen_urls = load_scan_history_urls(scan_history_path)

    skipped = 0
    unreachable = []
    all_new = []
    total_found = 0
    total_filtered_title = 0
    total_filtered_location = 0
    total_dupes = 0
    scanned_companies = 0
    today = date.today().isoformat()

    for company in companies:
        name = company.get("name", "?")
        careers_url = company.get("careers_url", "")
        provider, slug = detect_provider(careers_url)
        if not provider:
            skipped += 1
            continue

        scanned_companies += 1
        try:
            postings = PROVIDERS[provider](slug)
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError):
            unreachable.append(name)
            append_tsv(portal_health_path, PORTAL_HEALTH_HEADER,
                       [f"{today}T00:00:00.000Z", name, "unreachable"])
            continue

        append_tsv(portal_health_path, PORTAL_HEALTH_HEADER,
                   [f"{today}T00:00:00.000Z", name, "reachable"])
        total_found += len(postings)

        for p in postings:
            if positive and not title_matches(p["title"], positive):
                total_filtered_title += 1
                continue
            if negative and title_matches(p["title"], negative):
                total_filtered_title += 1
                continue
            if not location_allowed(p["location"], location_filter):
                total_filtered_location += 1
                continue
            if p["url"] in seen_urls:
                total_dupes += 1
                continue
            seen_urls.add(p["url"])
            entry = {"company": name, "title": p["title"], "location": p["location"],
                      "posted_at": p["posted_at"], "url": p["url"]}
            all_new.append(entry)
            append_tsv(scan_history_path, SCAN_HISTORY_HEADER,
                       [p["url"], today, PROVIDER_TAG[provider], p["title"], name,
                        "added", p["location"], "", p["posted_at"], "", "",
                        normalize_company(name)])

    jobspy_config = config.get("jobspy") or {}
    jobspy_errors = 0
    if jobspy_config.get("enabled") and positive:
        if jobspy_available():
            sites = jobspy_config.get("sites") or ["indeed"]
            results_wanted = jobspy_config.get("results_wanted", 20)
            country_indeed = jobspy_config.get("country_indeed", "usa")
            search_location = jobspy_config.get("location", "")
            for keyword in positive:
                try:
                    postings = fetch_jobspy(keyword, sites, results_wanted, country_indeed,
                                             search_location)
                except Exception:
                    jobspy_errors += 1
                    continue
                total_found += len(postings)
                for p in postings:
                    if negative and title_matches(p["title"], negative):
                        total_filtered_title += 1
                        continue
                    if not location_allowed(p["location"], location_filter):
                        total_filtered_location += 1
                        continue
                    if p["url"] in seen_urls:
                        total_dupes += 1
                        continue
                    seen_urls.add(p["url"])
                    entry = {"company": p["company"], "title": p["title"],
                              "location": p["location"], "posted_at": p["posted_at"],
                              "url": p["url"]}
                    all_new.append(entry)
                    append_tsv(scan_history_path, SCAN_HISTORY_HEADER,
                               [p["url"], today, p["site"], p["title"], p["company"],
                                "added", p["location"], "", p["posted_at"], "", "",
                                normalize_company(p["company"])])
        else:
            jobspy_errors += 1

    if all_new:
        append_pipeline_entries(pipeline_path, all_new)

    append_tsv(scan_runs_path, SCAN_RUNS_HEADER,
               [f"{today}T00:00:00.000Z", "completed", scanned_companies, 0,
                total_found, total_filtered_title, 0, total_filtered_location, 0, 0,
                0, 0, total_dupes, len(all_new), len(unreachable), 0, 0, 0, 0])

    return {
        "scanned_companies": scanned_companies, "skipped": skipped,
        "total_found": total_found, "total_filtered_title": total_filtered_title,
        "total_filtered_location": total_filtered_location, "total_dupes": total_dupes,
        "unreachable": unreachable, "all_new": all_new, "date": today,
        "jobspy_enabled": bool(jobspy_config.get("enabled")),
        "jobspy_ok": jobspy_config.get("enabled") and jobspy_available(),
        "jobspy_errors": jobspy_errors,
    }


def main(argv):
    base_path = "."
    if "--json" in argv:
        # Machine-readable mode, used by dashboard.py to shell out to a real
        # subprocess (not just a thread) — see run_scan_subprocess() docstring
        # for why: jobspy's tls_client dependency hung indefinitely when its
        # scrape call ran inside a Textual @work(thread=True) worker thread
        # instead of a process's own main thread. A real subprocess sidesteps
        # whatever that interaction is, and lets the caller enforce a timeout.
        try:
            result = run_scan(base_path)
        except FileNotFoundError:
            print(json.dumps({"error": "portals.yml not found"}))
            return 1
        print(json.dumps(result))
        return 0

    try:
        result = run_scan(base_path)
    except FileNotFoundError:
        print("Error: portals.yml not found. Run onboarding first.", file=sys.stderr)
        return 1

    print(f"Scanning {result['scanned_companies']} companies; 0 local parser; "
          f"{result['skipped']} skipped — no provider matched via providers")
    print()
    print("━" * 45)
    print(f"Portal Scan — {result['date']}")
    print("━" * 45)
    print(f"Companies scanned:     {result['scanned_companies']}")
    print(f"Total jobs found:      {result['total_found']}")
    print(f"Filtered by title:     {result['total_filtered_title']} removed")
    print(f"Duplicates:            {result['total_dupes']} skipped")
    print(f"New offers added:      {len(result['all_new'])}")
    print()

    if result["unreachable"]:
        print(f"⚠️  {len(result['unreachable'])} target(s) unreachable (slug?): "
              f"{', '.join(result['unreachable'])} — run: python3 verify_portals.py")
        print()

    if result["jobspy_enabled"] and not result["jobspy_ok"]:
        print("⚠️  jobspy is enabled in portals.yml but not installed/usable "
              "(needs Python 3.10+ and `pip install python-jobspy`) — skipped.")
        print()
    elif result["jobspy_errors"]:
        print(f"⚠️  jobspy: {result['jobspy_errors']} search(es) failed (network/site issue).")
        print()

    if result["all_new"]:
        print("New offers:")
        for e in result["all_new"]:
            print(f"  + {e['company']} | {e['title']} | {e['location']}")
        print()

    print("Results saved to data/pipeline.md and data/scan-history.tsv")
    print()
    print("→ Run `python3 pipeline.py` (or the tracker tools) to evaluate new offers.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
