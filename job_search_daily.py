name: Daily .NET Job Search

on:
  schedule:
    - cron: "30 4 * * *"   # 10:00 AM IST = 04:30 UTC
  workflow_dispatch:         # manual trigger from Actions tab

jobs:
  job-search:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install anthropic

      - name: Run job search
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          EMAIL_SENDER:      ${{ secrets.EMAIL_SENDER }}
          EMAIL_PASSWORD:    ${{ secrets.EMAIL_PASSWORD }}
          EMAIL_RECIPIENT:   ${{ secrets.EMAIL_RECIPIENT }}
          RAPIDAPI_KEY:      ${{ secrets.RAPIDAPI_KEY }}
          ADZUNA_APP_ID:     ${{ secrets.ADZUNA_APP_ID }}
          ADZUNA_APP_KEY:    ${{ secrets.ADZUNA_APP_KEY }}
          OUTPUT_FOLDER:     /tmp/JobSearchResults
        run: python job_search_daily.py

      - name: Upload CSVs as artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: job-results-${{ github.run_id }}
          path: /tmp/JobSearchResults/*.csv
          if-no-files-found: warn
          retention-days: 30
