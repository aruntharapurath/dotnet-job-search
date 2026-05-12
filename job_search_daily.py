"""
Daily .NET Job Search — Arun Thara Purath
=========================================
Sources  : JSearch API (RapidAPI) + Adzuna API — both reliable from GitHub Actions
Scoring  : Claude API scores each job 1–10 against your resume
Dedup    : SQLite — only new jobs are emailed each day
Output   : Two sections in email + two CSVs
             1. India jobs (product cos + GCC centres)
             2. Remote/Global jobs (EU / Canada product cos hiring from India)
"""

import os, json, sqlite3, csv, smtplib, time, hashlib, re
from datetime import date, datetime
import urllib.request, urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import anthropic

# ─────────────────────────────────────────────────────────────
# CONFIGURATION — set all of these as GitHub Secrets
# ─────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY",  "")
EMAIL_SENDER       = os.getenv("EMAIL_SENDER",       "")
EMAIL_PASSWORD     = os.getenv("EMAIL_PASSWORD",     "")
EMAIL_RECIPIENT    = os.getenv("EMAIL_RECIPIENT",    "arun.tharapurath@gmail.com")
RAPIDAPI_KEY       = os.getenv("RAPIDAPI_KEY",       "")   # from rapidapi.com → JSearch
ADZUNA_APP_ID      = os.getenv("ADZUNA_APP_ID",      "")   # from adzuna.com/developers
ADZUNA_APP_KEY     = os.getenv("ADZUNA_APP_KEY",     "")
OUTPUT_FOLDER      = os.getenv("OUTPUT_FOLDER",      "/tmp/JobSearchResults")
DB_PATH            = os.path.join(OUTPUT_FOLDER, "seen_jobs.db")

MIN_SCORE = 7

# ─────────────────────────────────────────────────────────────
# CANDIDATE PROFILE
# ─────────────────────────────────────────────────────────────
PROFILE = """
Name      : Arun Thara Purath
Experience: 10 years — Full Stack / Senior Software Engineer
Backend   : .NET Core, C#, ASP.NET Core, Web API, Entity Framework
Cloud     : Azure (AZ-204 in progress), Docker, Kubernetes, Terraform, CI/CD
Frontend  : Angular, React, TypeScript, JavaScript
Databases : SQL Server, MongoDB, CosmosDB, Redis, MySQL
Arch      : Microservices, Distributed Systems, Serverless, Monolith-to-Micro migration
Other     : Kafka, GraphQL, OAuth/JWT, Node.js, Python, AI tooling (Prompt Flow)
Current   : Sr Software Engineer at Intelex Technology (SaaS product co), Bangalore
Preference: Product companies, SaaS, MNCs, GCC centres — NOT service firms or consultancies
"""

# ─────────────────────────────────────────────────────────────
# EXCLUSION KEYWORDS
# ─────────────────────────────────────────────────────────────
EXCLUDE_KEYWORDS = [
    "tata consultancy", "infosys", "wipro", "hcl technologies", "tech mahindra",
    "cognizant", "mphasis", "hexaware", "ltimindtree", "mindtree", "persistent systems",
    "mastek", "cyient", "kpit", "birlasoft", "sonata software", "zensar", "sasken",
    "niit technologies", "firstsource", "syntel",
    "deloitte", "kpmg", "pricewaterhousecoopers", "ernst & young",
    "accenture", "mckinsey", "boston consulting group", "bain & company",
    "booz allen", "ibm consulting", "oliver wyman", "roland berger",
    "randstad", "adecco", "manpowergroup", "robert half", "hays", "michael page",
    "kelly services", "allegis", "experis", "collabera", "mindlance",
    "staffing solutions", "recruitment agency", "it staffing",
    "it services company", "outsourcing company", "body shopping"
]

# ─────────────────────────────────────────────────────────────
# JSEARCH API  (RapidAPI — free tier: 150 req/month)
# We make 4 calls/day = ~120/month — within free tier
# ─────────────────────────────────────────────────────────────

JSEARCH_QUERIES_INDIA = [
    ("Senior .NET Core Engineer Bangalore", "IN"),
    ("Senior .NET Core microservices Bangalore", "IN"),
    ("Senior .NET Engineer Azure Bangalore", "IN"),
    (".NET Core cloud engineer Bangalore", "IN"),
    (".NET engineer GCC product company Bangalore", "IN"),
    ("Senior .NET Engineer GCC Bangalore", "IN"),
    (".NET Core microservices GCC India", "IN"),
]

JSEARCH_QUERIES_REMOTE = [
    ("Senior .NET Core Engineer remote India", ""),
    ("Senior .NET Engineer remote Europe", ""),
    (".NET Core microservices remote Europe", ""),
    ("Senior C# .NET remote Europe", ""),
    ("Senior .NET Engineer remote Canada", "CA"),
    (".NET Core Azure remote", "GB"),
    ("Senior .NET Core Engineer remote", "DE"),
    ("Senior .NET Engineer remote", "NL"),
    (".NET microservices remote", "FR"),
    ("Senior .NET Core Engineer remote", "SE"),
    (".NET Azure microservices remote", "PL"),
]

def jsearch_fetch(query: str, country: str) -> list:
    """Fetch jobs from JSearch API."""
    jobs = []
    if not RAPIDAPI_KEY:
        print("  ⚠  RAPIDAPI_KEY not set — skipping JSearch")
        return jobs
    params = urllib.parse.urlencode({
        "query":           query,
        "page":            "1",
        "num_pages":       "1",
        "date_posted":     "week",
        "employment_types":"FULLTIME",
    })
    if country:
        params += "&" + urllib.parse.urlencode({"country": country})

    url = f"https://jsearch.p.rapidapi.com/search?{params}"
    req = urllib.request.Request(url, headers={
        "X-RapidAPI-Key":  RAPIDAPI_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        for j in data.get("data", []):
            jobs.append({
                "title":    j.get("job_title", ""),
                "company":  j.get("employer_name", ""),
                "location": f"{j.get('job_city','') or ''} {j.get('job_country','')}".strip(),
                "link":     j.get("job_apply_link") or j.get("job_google_link", ""),
                "desc":     (j.get("job_description") or "")[:600],
                "pubdate":  j.get("job_posted_at_datetime_utc", ""),
            })
    except Exception as e:
        print(f"  ⚠  JSearch error ({query[:40]}): {e}")
    return jobs


def collect_jsearch(queries: list) -> list:
    seen, results = set(), []
    for query, country in queries:
        print(f"  JSearch: {query}")
        for job in jsearch_fetch(query, country):
            key = f"{job['title'].lower()}|{job['company'].lower()}"
            if key not in seen:
                seen.add(key)
                results.append(job)
        time.sleep(1)
    return results


# ─────────────────────────────────────────────────────────────
# ADZUNA API  (free: 250 req/day — very generous)
# Covers India (in), UK (gb), Germany (de), Netherlands (nl), France (fr), Sweden (se), Poland (pl), Austria (at), Canada (ca)
# ─────────────────────────────────────────────────────────────

ADZUNA_INDIA_SEARCHES = [
    ("in", "senior dotnet core engineer Bangalore"),
    ("in", "senior c# azure microservices Bangalore"),
    ("in", "dotnet core GCC Bangalore"),
    ("in", "senior dotnet engineer product company Bangalore"),
    ("in", "dotnet microservices GCC India"),
]

# Europe country codes: gb=UK, de=Germany, nl=Netherlands, fr=France,
# se=Sweden, pl=Poland, at=Austria, be=Belgium, ch=Switzerland
ADZUNA_REMOTE_SEARCHES = [
    ("gb", "senior dotnet core remote"),
    ("gb", "senior c# microservices remote"),
    ("de", "senior dotnet engineer remote"),
    ("nl", "dotnet core azure remote"),
    ("fr", "senior dotnet engineer remote"),
    ("se", "senior dotnet core remote"),
    ("pl", "dotnet core microservices remote"),
    ("at", "senior dotnet engineer remote"),
    ("ca", "senior dotnet engineer remote"),
    ("ca", "dotnet core azure remote"),
]

def adzuna_fetch(country: str, query: str) -> list:
    """Fetch jobs from Adzuna API."""
    jobs = []
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("  ⚠  Adzuna credentials not set — skipping Adzuna")
        return jobs
    params = urllib.parse.urlencode({
        "app_id":        ADZUNA_APP_ID,
        "app_key":       ADZUNA_APP_KEY,
        "results_per_page": "20",
        "what":          query,
        "sort_by":       "date",
        "max_days_old":  "7",
        "content-type":  "application/json",
    })
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "JobSearchBot/1.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        for j in data.get("results", []):
            loc = j.get("location", {})
            loc_str = ", ".join(loc.get("area", [])[-2:]) if loc else ""
            jobs.append({
                "title":    j.get("title", ""),
                "company":  j.get("company", {}).get("display_name", ""),
                "location": loc_str,
                "link":     j.get("redirect_url", ""),
                "desc":     re.sub(r"<[^>]+>", " ", j.get("description", ""))[:600],
                "pubdate":  j.get("created", ""),
            })
    except Exception as e:
        print(f"  ⚠  Adzuna error ({country}/{query[:30]}): {e}")
    return jobs


def collect_adzuna(searches: list) -> list:
    seen, results = set(), []
    for country, query in searches:
        print(f"  Adzuna [{country.upper()}]: {query}")
        for job in adzuna_fetch(country, query):
            key = f"{job['title'].lower()}|{job['company'].lower()}"
            if key not in seen:
                seen.add(key)
                results.append(job)
        time.sleep(1)
    return results


# ─────────────────────────────────────────────────────────────
# EXCLUSION FILTER
# ─────────────────────────────────────────────────────────────

def is_excluded(job: dict) -> bool:
    haystack = (job.get("company", "") + " " + job.get("desc", "")).lower()
    return any(kw in haystack for kw in EXCLUDE_KEYWORDS)


# ─────────────────────────────────────────────────────────────
# SQLITE DEDUPLICATION
# ─────────────────────────────────────────────────────────────

def init_db():
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_jobs (
            id TEXT PRIMARY KEY, title TEXT, company TEXT, seen_date TEXT
        )
    """)
    conn.commit()
    return conn

def job_id(job: dict) -> str:
    raw = f"{job.get('title','').lower().strip()}|{job.get('company','').lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()

def filter_new_jobs(conn, jobs: list) -> list:
    new = []
    for job in jobs:
        jid = job_id(job)
        if not conn.execute("SELECT 1 FROM seen_jobs WHERE id=?", (jid,)).fetchone():
            new.append(job)
            conn.execute("INSERT INTO seen_jobs VALUES (?,?,?,?)",
                         (jid, job.get("title",""), job.get("company",""), date.today().isoformat()))
    conn.commit()
    return new


# ─────────────────────────────────────────────────────────────
# CLAUDE SCORING
# ─────────────────────────────────────────────────────────────

def score_jobs_with_claude(jobs: list, category: str) -> list:
    if not jobs:
        return []
    client, scored = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY), []

    for i in range(0, len(jobs), 10):
        chunk = jobs[i:i+10]
        jobs_json = json.dumps([
            {"index": idx, "title": j.get("title",""),
             "company": j.get("company",""), "location": j.get("location",""),
             "desc": j.get("desc","")}
            for idx, j in enumerate(chunk)
        ], indent=2)

        prompt = f"""
You are a job fit analyst. Evaluate these {category} job listings for the candidate below.

CANDIDATE:
{PROFILE}

JOBS:
{jobs_json}

Return ONLY a JSON array (no markdown, no preamble):
[
  {{
    "index": <same as input>,
    "score": <1-10>,
    "why_good_fit": "<1-2 sentences, specific about tech stack match>",
    "red_flags": "<concerns or empty string>"
  }}
]

Scoring guide:
9-10 = Strong .NET Core/Azure/microservices match + product/SaaS/GCC company
7-8  = Good match, minor gaps
5-6  = Partial match
1-4  = Poor fit — wrong stack, service firm, junior role
"""
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-20250514", max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            text = resp.content[0].text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            results = {r["index"]: r for r in json.loads(text)}
            for idx, job in enumerate(chunk):
                r = results.get(idx, {})
                job.update({
                    "score":        r.get("score", 0),
                    "why_good_fit": r.get("why_good_fit", ""),
                    "red_flags":    r.get("red_flags", ""),
                })
                scored.append(job)
        except Exception as e:
            print(f"  ⚠  Scoring error: {e}")
            for job in chunk:
                job.update({"score": 0, "why_good_fit": "Scoring failed", "red_flags": str(e)})
                scored.append(job)
        time.sleep(1)

    return sorted(scored, key=lambda x: x.get("score", 0), reverse=True)


# ─────────────────────────────────────────────────────────────
# CSV
# ─────────────────────────────────────────────────────────────

FIELDS = ["score","title","company","location","why_good_fit","red_flags","link","pubdate"]

def save_csv(jobs: list, label: str) -> str:
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    path = os.path.join(OUTPUT_FOLDER, f"{label}_{date.today().isoformat()}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(jobs)
    print(f"  Saved {len(jobs)} jobs → {path}")
    return path


# ─────────────────────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────────────────────

def score_color(s):
    if s >= 9:  return "#1a7a1a"
    if s >= 7:  return "#2d7dd2"
    if s >= 5:  return "#e07b00"
    return "#999"

def jobs_table_html(jobs, empty_msg):
    if not jobs:
        return f'<p style="color:#999;font-style:italic">{empty_msg}</p>'
    rows = "".join(f"""
        <tr style="background:{'#f9fafe' if i%2==0 else 'white'}">
          <td style="padding:8px;border:1px solid #ddd;text-align:center">
            <strong style="color:{score_color(j.get('score',0))}">{j.get('score',0)}/10</strong>
          </td>
          <td style="padding:8px;border:1px solid #ddd"><strong>{j.get('title','')}</strong></td>
          <td style="padding:8px;border:1px solid #ddd">{j.get('company','')}</td>
          <td style="padding:8px;border:1px solid #ddd">{j.get('location','')}</td>
          <td style="padding:8px;border:1px solid #ddd;font-size:12px">{j.get('why_good_fit','')}</td>
          <td style="padding:8px;border:1px solid #ddd;font-size:12px;color:#c0392b">{j.get('red_flags','')}</td>
          <td style="padding:8px;border:1px solid #ddd">
            {'<a href="' + j.get("link","#") + '">View</a>' if j.get("link") else "—"}
          </td>
        </tr>""" for i, j in enumerate(jobs))
    return f"""
    <table style="border-collapse:collapse;width:100%;font-size:13px;margin-bottom:24px">
      <thead><tr style="background:#1a1a2e;color:white">
        {''.join(f'<th style="padding:10px;border:1px solid #444">{h}</th>'
          for h in ["Score","Role","Company","Location","Why It Fits","Red Flags","Link"])}
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""

def build_email_html(india_top, india_all, remote_top, remote_all):
    today = date.today().strftime("%B %d, %Y")
    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:1100px;margin:auto;padding:20px">
      <h1 style="color:#1a1a2e">🔍 Daily .NET Job Search — {today}</h1>
      <p style="color:#888">New jobs only &nbsp;·&nbsp; Min score to appear in email: <strong>{MIN_SCORE}/10</strong></p>

      <h2 style="color:#2d7dd2;border-bottom:2px solid #2d7dd2;padding-bottom:6px">
        🇮🇳 India — Product Companies &amp; GCC Centres
        <span style="font-size:13px;font-weight:normal;color:#666">
          ({len(india_top)} high-fit / {len(india_all)} new today)
        </span>
      </h2>
      {jobs_table_html(india_top, "No high-scoring India roles today — check the attached CSV.")}

      <h2 style="color:#1a7a1a;border-bottom:2px solid #1a7a1a;padding-bottom:6px">
        🌍 Remote — EU &amp; Canada Product Companies
        <span style="font-size:13px;font-weight:normal;color:#666">
          ({len(remote_top)} high-fit / {len(remote_all)} new today)
        </span>
      </h2>
      {jobs_table_html(remote_top, "No high-scoring remote roles today — check the attached CSV.")}

      <p style="color:#bbb;font-size:11px;margin-top:30px">
        Full CSVs attached. Seen-jobs database ensures no duplicates across days.
      </p>
    </body></html>"""

def send_email(html: str, attachments: list):
    today = date.today().strftime("%B %d, %Y")
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"🔍 .NET Job Leads — {today}"
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECIPIENT
    msg.attach(MIMEText(html, "html"))
    for path in attachments:
        if os.path.exists(path):
            with open(path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition",
                                f"attachment; filename={os.path.basename(path)}")
                msg.attach(part)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(EMAIL_SENDER, EMAIL_PASSWORD)
        s.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
    print(f"  ✉  Email sent to {EMAIL_RECIPIENT}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"  Daily .NET Job Search — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    conn = init_db()

    # ── Collect ──────────────────────────────────────────────
    print("📡 Fetching India jobs…")
    india_raw = collect_jsearch(JSEARCH_QUERIES_INDIA) + collect_adzuna(ADZUNA_INDIA_SEARCHES)
    print(f"   {len(india_raw)} raw India listings\n")

    print("📡 Fetching Remote/Global jobs…")
    remote_raw = collect_jsearch(JSEARCH_QUERIES_REMOTE) + collect_adzuna(ADZUNA_REMOTE_SEARCHES)
    print(f"   {len(remote_raw)} raw remote listings\n")

    # ── Filter ───────────────────────────────────────────────
    india_filtered  = [j for j in india_raw  if not is_excluded(j)]
    remote_filtered = [j for j in remote_raw if not is_excluded(j)]
    print(f"🚫 After exclusion: {len(india_filtered)} India | {len(remote_filtered)} Remote\n")

    # ── Deduplicate ──────────────────────────────────────────
    india_new  = filter_new_jobs(conn, india_filtered)
    remote_new = filter_new_jobs(conn, remote_filtered)
    print(f"✅ New jobs today: {len(india_new)} India | {len(remote_new)} Remote\n")

    if not india_new and not remote_new:
        print("No new jobs today — no email sent.")
        return

    # ── Score ────────────────────────────────────────────────
    print("🤖 Scoring India jobs with Claude…")
    india_scored  = score_jobs_with_claude(india_new,  "India GCC / product company")

    print("🤖 Scoring Remote jobs with Claude…")
    remote_scored = score_jobs_with_claude(remote_new, "EU / Canada remote product company")

    india_top  = [j for j in india_scored  if j.get("score", 0) >= MIN_SCORE]
    remote_top = [j for j in remote_scored if j.get("score", 0) >= MIN_SCORE]
    print(f"\n🌟 High-fit (score>={MIN_SCORE}): {len(india_top)} India | {len(remote_top)} Remote")

    # ── Save + Email ─────────────────────────────────────────
    print("\n💾 Saving CSVs…")
    india_csv  = save_csv(india_scored,  "india_jobs")
    remote_csv = save_csv(remote_scored, "remote_jobs")

    print("\n✉  Sending email…")
    html = build_email_html(india_top, india_new, remote_top, remote_new)
    send_email(html, [india_csv, remote_csv])

    print(f"\n✅ Done! {len(india_top)+len(remote_top)} high-fit roles emailed.\n")


if __name__ == "__main__":
    main()
