"""
Daily .NET Job Search — Arun Thara Purath
=========================================
Sources  : LinkedIn RSS + Indeed RSS (real listings, no hallucination)
Scoring  : Claude API scores each job 1–10 against your resume
Dedup    : SQLite — only new jobs are emailed each day
Output   : Two sections in email + two CSVs
             1. India jobs (product cos + GCC centres, no service/consulting firms)
             2. Remote/Global jobs (EU / Canada product cos hiring remotely from India)
Scheduler: Windows Task Scheduler OR GitHub Actions (env-var friendly)
"""

import os, json, sqlite3, csv, smtplib, time, hashlib, re
from datetime import date, datetime
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import anthropic

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# Set these as environment variables (recommended) or hardcode.
# ─────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "your-anthropic-api-key-here")
EMAIL_SENDER      = os.getenv("EMAIL_SENDER",      "your-gmail@gmail.com")
EMAIL_PASSWORD    = os.getenv("EMAIL_PASSWORD",    "your-app-password-here")
EMAIL_RECIPIENT   = os.getenv("EMAIL_RECIPIENT",   "arun.tharapurath@gmail.com")
OUTPUT_FOLDER     = os.getenv("OUTPUT_FOLDER",     r"C:\JobSearchResults")
DB_PATH           = os.path.join(OUTPUT_FOLDER, "seen_jobs.db")

MIN_SCORE = 7   # Only email jobs scoring >= this

# ─────────────────────────────────────────────────────────────
# CANDIDATE PROFILE  (used in Claude scoring prompt)
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
Preference: Product companies, SaaS, MNCs / GCC centres — NOT service firms or consultancies
"""

# ─────────────────────────────────────────────────────────────
# EXCLUSION KEYWORDS  (checked against company name + description)
# ─────────────────────────────────────────────────────────────
EXCLUDE_KEYWORDS = [
    # Indian IT service cos
    "tata consultancy","infosys","wipro","hcl technologies","tech mahindra",
    "cognizant","mphasis","hexaware","ltimindtree","mindtree","persistent systems",
    "mastek","cyient","kpit","birlasoft","sonata software","zensar","sasken",
    "niit technologies","firstsource","syntel",
    # Big 4 & global consulting
    "deloitte","kpmg","pricewaterhousecoopers","ernst & young",
    "accenture","mckinsey","boston consulting group","bain & company",
    "booz allen","ibm consulting","oliver wyman","roland berger",
    # Staffing / recruitment
    "allegis","collabera",
    # Generic signals in job descriptions
    "staffing solutions","recruitment agency","it staffing",
    "it services company","outsourcing company","body shopping"
]

# ─────────────────────────────────────────────────────────────
# RSS FEED DEFINITIONS
# ─────────────────────────────────────────────────────────────

def linkedin_rss(keywords: str, location: str) -> str:
    base   = "https://www.linkedin.com/jobs/search/"
    params = urllib.parse.urlencode({
        "keywords": keywords,
        "location": location,
        "f_TPR":    "r604800",  # last 7 days
    })
    return f"{base}?{params}"

def indeed_rss(query: str, location: str, remote: bool = False) -> str:
    params = {"q": query, "l": location, "sort": "date", "limit": "25", "fromage": "7"}
    if remote:
        params["remotejob"] = "1"
    return "https://indeed.com/rss?" + urllib.parse.urlencode(params)

# India: product cos + GCC centres
INDIA_FEEDS = [
    linkedin_rss("Senior .NET Core Engineer",         "Bangalore, India"),
    linkedin_rss("Senior .NET Core microservices",    "Bangalore, India"),
    linkedin_rss("Senior .NET Engineer Azure",        "Bangalore, India"),
    linkedin_rss(".NET Core cloud engineer",          "Bangalore, India"),
    linkedin_rss(".NET engineer GCC product company", "Bangalore, India"),
    indeed_rss("senior .net core engineer",           "Bangalore, India"),
    indeed_rss(".net core azure microservices",       "Bangalore, India"),
]

# Remote/Global: EU & Canada product cos open to India-based engineers
REMOTE_FEEDS = [
    linkedin_rss("Senior .NET Core Engineer remote",  "Europe"),
    linkedin_rss("Senior .NET Engineer remote India", ""),
    linkedin_rss(".NET microservices remote",         "Canada"),
    linkedin_rss("Senior C# .NET remote",             "Netherlands"),
    linkedin_rss("Senior .NET engineer remote",       "Germany"),
    linkedin_rss(".NET Core Azure remote",            "United Kingdom"),
    indeed_rss("senior .net core remote",             "",    remote=True),
    indeed_rss(".net core azure remote india",        "",    remote=True),
]


# ─────────────────────────────────────────────────────────────
# RSS PARSING
# ─────────────────────────────────────────────────────────────

def fetch_rss(url: str) -> list:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobSearchBot/1.0)"}
    jobs = []
    try:
        req  = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=15)
        root = ET.fromstring(resp.read())
        channel = root.find("channel")
        if channel is None:
            return jobs
        for item in channel.findall("item"):
            title   = (item.findtext("title")       or "").strip()
            company = (item.findtext("source")       or "").strip()
            link    = (item.findtext("link")         or "").strip()
            desc    = (item.findtext("description")  or "").strip()
            pubdate = (item.findtext("pubDate")      or "").strip()
            # LinkedIn encodes "Role at Company" in the title
            if " at " in title and not company:
                parts   = title.rsplit(" at ", 1)
                title   = parts[0].strip()
                company = parts[1].strip()
            jobs.append({
                "title":    title,
                "company":  company,
                "link":     link,
                "desc":     re.sub(r"<[^>]+>", " ", desc)[:600],
                "pubdate":  pubdate,
                "location": "",
            })
    except Exception as e:
        print(f"  ⚠  Feed error ({url[:70]}): {e}")
    return jobs


def collect_jobs(feeds: list) -> list:
    seen, all_jobs = set(), []
    for url in feeds:
        print(f"  Fetching: {url[:80]}…")
        for job in fetch_rss(url):
            key = f"{job['title'].lower()}|{job['company'].lower()}"
            if key not in seen:
                seen.add(key)
                all_jobs.append(job)
        time.sleep(1)
    return all_jobs


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
            id        TEXT PRIMARY KEY,
            title     TEXT,
            company   TEXT,
            seen_date TEXT
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
        chunk     = jobs[i:i+10]
        jobs_json = json.dumps([
            {"index": idx, "title": j.get("title",""),
             "company": j.get("company",""), "desc": j.get("desc","")}
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
    "location": "<city / Remote / Hybrid — extract from title or description>",
    "why_good_fit": "<1-2 sentences, specific about tech stack match>",
    "red_flags": "<concerns or empty string>"
  }}
]

Scoring guide:
9-10 = Strong .NET Core/Azure/microservices match + product/SaaS/GCC company
7-8  = Good match, minor gaps or neutral company type
5-6  = Partial match — different stack or unclear company type
1-4  = Poor fit — wrong stack, service firm, junior, or unrelated role
"""
        try:
            resp  = client.messages.create(
                model="claude-sonnet-4-20250514", max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            text    = resp.content[0].text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            results = {r["index"]: r for r in json.loads(text)}
            for idx, job in enumerate(chunk):
                r = results.get(idx, {})
                job.update({
                    "score":        r.get("score", 0),
                    "location":     r.get("location", ""),
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
# CSV EXPORT
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
            {'<a href="' + j.get("link","#") + '">View</a>' if j.get("link") else '—'}
          </td>
        </tr>""" for i, j in enumerate(jobs))
    return f"""
    <table style="border-collapse:collapse;width:100%;font-size:13px;margin-bottom:24px">
      <thead><tr style="background:#1a1a2e;color:white">
        {''.join(f'<th style="padding:10px;border:1px solid #444">{h}</th>' for h in
          ["Score","Role","Company","Location","Why It Fits","Red Flags","Link"])}
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""

def build_email_html(india_top, india_all, remote_top, remote_all):
    today = date.today().strftime("%B %d, %Y")
    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:1100px;margin:auto;padding:20px">
      <h1 style="color:#1a1a2e;margin-bottom:4px">🔍 Daily .NET Job Search</h1>
      <p style="color:#888;margin-top:0">{today} &nbsp;·&nbsp; New jobs only &nbsp;·&nbsp;
         Min score to appear: <strong>{MIN_SCORE}/10</strong></p>

      <h2 style="color:#2d7dd2;border-bottom:2px solid #2d7dd2;padding-bottom:6px">
        🇮🇳 India — Product Companies &amp; GCC Centres &nbsp;
        <span style="font-size:13px;font-weight:normal;color:#666">
          {len(india_top)} high-fit &nbsp;/&nbsp; {len(india_all)} new today
        </span>
      </h2>
      {jobs_table_html(india_top, "No high-scoring India roles found today — check the CSV for all listings.")}

      <h2 style="color:#1a7a1a;border-bottom:2px solid #1a7a1a;padding-bottom:6px">
        🌍 Remote — EU &amp; Canada Product Companies &nbsp;
        <span style="font-size:13px;font-weight:normal;color:#666">
          {len(remote_top)} high-fit &nbsp;/&nbsp; {len(remote_all)} new today
        </span>
      </h2>
      {jobs_table_html(remote_top, "No high-scoring remote roles found today — check the CSV for all listings.")}

      <p style="color:#bbb;font-size:11px;margin-top:30px">
        Full CSVs (all scored jobs) attached and saved to {OUTPUT_FOLDER}<br>
        Seen-jobs database: {DB_PATH}
      </p>
    </body></html>"""

def send_email(html: str, attachments: list):
    today = date.today().strftime("%B %d, %Y")
    msg   = MIMEMultipart("mixed")
    msg["Subject"] = f"🔍 .NET Job Leads — {today}"
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECIPIENT
    msg.attach(MIMEText(html, "html"))
    for path in attachments:
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

    print("📡 Fetching India feeds…")
    india_raw = collect_jobs(INDIA_FEEDS)
    print(f"   {len(india_raw)} raw listings\n")

    print("📡 Fetching Remote/Global feeds…")
    remote_raw = collect_jobs(REMOTE_FEEDS)
    print(f"   {len(remote_raw)} raw listings\n")

    india_filtered  = [j for j in india_raw  if not is_excluded(j)]
    remote_filtered = [j for j in remote_raw if not is_excluded(j)]
    print(f"🚫 After exclusion filter: {len(india_filtered)} India | {len(remote_filtered)} Remote\n")

    india_new  = filter_new_jobs(conn, india_filtered)
    remote_new = filter_new_jobs(conn, remote_filtered)
    print(f"✅ New jobs today: {len(india_new)} India | {len(remote_new)} Remote\n")

    if not india_new and not remote_new:
        print("No new jobs today — no email sent.")
        return

    print("🤖 Scoring India jobs…")
    india_scored  = score_jobs_with_claude(india_new,  "India GCC / product company")

    print("🤖 Scoring Remote jobs…")
    remote_scored = score_jobs_with_claude(remote_new, "EU / Canada remote product company")

    india_top  = [j for j in india_scored  if j.get("score", 0) >= MIN_SCORE]
    remote_top = [j for j in remote_scored if j.get("score", 0) >= MIN_SCORE]
    print(f"\n🌟 High-fit (score>={MIN_SCORE}): {len(india_top)} India | {len(remote_top)} Remote")

    print("\n💾 Saving CSVs…")
    india_csv  = save_csv(india_scored,  "india_jobs")
    remote_csv = save_csv(remote_scored, "remote_jobs")

    print("\n✉  Sending email…")
    html = build_email_html(india_top, india_new, remote_top, remote_new)
    send_email(html, [india_csv, remote_csv])

    print(f"\n✅ Done! {len(india_top)+len(remote_top)} high-fit roles emailed.\n")


if __name__ == "__main__":
    main()
