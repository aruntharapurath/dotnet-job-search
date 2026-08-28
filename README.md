# 🔍 Daily .NET Job Search Automation

An automated job search pipeline that runs every day at **10:00 AM IST**, finds fresh .NET engineering roles, scores them against your resume using Claude AI, and delivers a curated email digest — no duplicates, no service companies, no noise.

---

## How It Works

```
JSearch API (RapidAPI)  +  Adzuna API
           ↓
    Collect raw listings
           ↓
  Exclude service firms / consultancies / Big 4
           ↓
  Deduplicate via SQLite (seen jobs never repeat)
           ↓
  Claude AI scores each job 1–10 against your resume
           ↓
  Email: only jobs scoring 7+ (two sections)
  CSV:   all scored jobs saved as artifacts
```

---

## What You Get Every Morning

**Section 1 — 🇮🇳 India: Product Companies & GCC Centres (Bangalore)**
- Senior .NET Core / Azure / Microservices roles
- Product companies and Global Capability Centres only


**Section 2 — 🌍 European & Canadian Companies: Remote from India**
- UK, Germany, Netherlands, France, Sweden, Poland, Austria, Canada
- Same stack focus: .NET Core, Azure, Microservices

Each job shows:
| Field | Description |
|---|---|
| Score | Claude's fit rating out of 10 |
| Role | Job title |
| Company | Employer name |
| Location | City / Remote / Hybrid |
| Why It Fits | Claude's reasoning specific to your stack |
| Red Flags | Any concerns flagged by Claude |
| Link | Direct apply link |

---

## Tech Stack

| Component | Tool |
|---|---|
| Job sources | JSearch (RapidAPI) + Adzuna API |
| AI scoring | Claude Sonnet (Anthropic API) |
| Deduplication | SQLite database |
| Scheduler | GitHub Actions (cron) |
| Notifications | Gmail (SMTP) |
| Output | HTML email + CSV attachments |

---

## Setup

### 1. API Keys You Need

| Service | Free Tier | Sign Up |
|---|---|---|
| Anthropic API | $20 credit on signup | console.anthropic.com |
| JSearch (RapidAPI) | 150 requests/month | rapidapi.com → search "JSearch" |
| Adzuna | 250 requests/day | developer.adzuna.com |
| Gmail App Password | Free | myaccount.google.com → Security → App Passwords |

### 2. GitHub Repository Secrets

Go to your repo → **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your `sk-ant-...` key |
| `EMAIL_SENDER` | Gmail address to send from |
| `EMAIL_PASSWORD` | Gmail App Password (16 chars, no spaces) |
| `EMAIL_RECIPIENT` | Where to deliver results |
| `RAPIDAPI_KEY` | Your RapidAPI key |
| `ADZUNA_APP_ID` | Your Adzuna App ID |
| `ADZUNA_APP_KEY` | Your Adzuna App Key |

### 3. Repository Structure

```
dotnet-job-search/
├── job_search_daily.py          # Main script
├── README.md                    # This file
└── .github/
    └── workflows/
        └── job_search.yml       # GitHub Actions scheduler
```

### 4. Trigger a Test Run

1. Go to the **Actions** tab in your repo
2. Click **Daily .NET Job Search** in the sidebar
3. Click **Run workflow** → **Run workflow**
4. Watch the logs — check your inbox within ~60 seconds

---

## Customisation

### Change the minimum score threshold
In `job_search_daily.py`, line 34:
```python
MIN_SCORE = 7  # raise to 8 for stricter filtering, lower to 6 for more results
```

### Add or remove search queries
```python
JSEARCH_QUERIES_INDIA = [
    ("Senior .NET Core Engineer Bangalore", "IN"),
    # add more here...
]

ADZUNA_INDIA_SEARCHES = [
    ("in", "senior dotnet core engineer Bangalore"),
    # add more here...
]
```

### Add companies to the exclusion list
```python
EXCLUDE_KEYWORDS = [
    "company name to exclude",
    # add more here...
]
```

### Change the schedule
In `job_search.yml`:
```yaml
- cron: "30 4 * * *"   # 04:30 UTC = 10:00 AM IST
```
Use [crontab.guru](https://crontab.guru) to generate a different time.

---

## Cost Estimate

| Service | Usage | Monthly Cost |
|---|---|---|
| Anthropic API | ~5,000 tokens/day | ~$1.50 |
| JSearch | ~18 calls/day → ~540/month | Free tier: 150/month — upgrade if needed |
| Adzuna | ~15 calls/day | Free (250/day limit) |
| GitHub Actions | ~2 min/day → ~60 min/month | Free (2,000 min/month limit) |
| **Total** | | **~$1.50/month** |

> **Note:** JSearch free tier is 150 requests/month. With 18 queries/day the script will exceed this after ~8 days. Either upgrade to a paid RapidAPI plan (~$10/month) or reduce the number of JSearch queries and rely more on Adzuna.

---

## Excluded Companies

The script automatically filters out:

**Indian IT Service Companies:** TCS, Infosys, Wipro, HCL, Tech Mahindra, Cognizant, Mphasis, Hexaware, LTIMindtree, Persistent Systems, and more.

**Big 4 & Global Consultancies:** Deloitte, KPMG, PwC, EY, Accenture, McKinsey, BCG, Bain, Booz Allen, and more.

**Staffing & Recruitment Firms:** Randstad, Adecco, Hays, Michael Page, Robert Half, and more.

---

## Troubleshooting

**No jobs found / 0 raw listings**
- Check that all 7 GitHub Secrets are set correctly
- Verify the `env:` section in `job_search.yml` passes all secrets to the script

**No email received**
- Check your spam folder
- Verify `EMAIL_PASSWORD` is the App Password, not your Gmail login password
- Make sure 2-Step Verification is enabled on your Google account

**Score always 0**
- Check `ANTHROPIC_API_KEY` is valid and has credit balance at console.anthropic.com

**JSearch hitting rate limits**
- Reduce `JSEARCH_QUERIES_INDIA` and `JSEARCH_QUERIES_REMOTE` lists
- Or upgrade to a paid RapidAPI plan
