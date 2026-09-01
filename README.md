# Daily News Briefing — Morocco 🇲🇦 & The Netherlands 🇳🇱

A **static** news site that pulls the latest headlines for Morocco and the
Netherlands from public RSS feeds into one clean page — no API key, no
database, no server of your own.

## How it works

There is no backend. A Python script runs on a schedule in GitHub Actions and
refreshes one file, `data.json`; the static page reads it:

```
GitHub cron (every 30 min)
      │  runs
      ▼
generate_data.py ──► news_client.py (RSS)
      │  writes, but only if content actually changed
      ▼
   data.json  ── committed & pushed ──► GitHub Pages serves it
      ▲
      │  fetched on load, refetched every 5 min & on tab focus
   index.html (client-side render, no build step)
```

- **`generate_data.py`** — the entry point. Fetches and writes `data.json`
  **and** `data.js` (a JS mirror for the offline case below). It *skips the
  write when nothing changed* (so the cron only commits when the news moved),
  and on a total feed outage it exits non-zero *without* overwriting, so the
  last good data stays published.
- **`news_client.py`** — merges each country's RSS/Atom feeds, dedupes, keeps
  the freshest items. One feed going down never blanks a country.
- **`summarizer.py`** — extractive summarizer, kept for the archived Flask
  preview; the static site no longer generates briefing text.
- **`index.html`** — the whole front end: dashboard UI rendered from
  `data.json`, mobile country switch, auto-refresh. No build step, no deps.
- **`data.js`** — a committed `window.__NEWS__ = {…}` snapshot. Browsers block
  `fetch()` on `file://` pages, so this is what lets you **double-click
  `index.html`** and still see the news; over HTTP the page fetches the live
  `data.json` instead.
- **`.github/workflows/update-news.yml`** — the scheduled job that keeps the
  data fresh and pushes it back.

## Set up hosting (GitHub Pages — free)

1. Push this folder to a GitHub repo.
2. In the repo, go to **Settings → Pages → Source** and pick **Deploy from a
   branch** → branch `main`, folder `/ (root)`, **Save**.
3. That's it. The workflow runs every 30 minutes (and any time you open
   **Actions → Update news data → Run workflow** to force it); `index.html`
   then serves live from Pages at `https://<user>.github.io/<repo>/`.

> GitHub's scheduled workflows can lag a few minutes under load, and the very
> first one only starts after a push to the default branch. Use the manual
> "Run workflow" button if you don't want to wait.

## Preview locally

**Double-click `index.html`** and it renders from the committed `data.js`
snapshot. For live re-fetching (picks up new `data.json` every few minutes),
run a server:

```bash
python generate_data.py     # refresh data.json + data.js
python -m http.server 5000  # then open http://127.0.0.1:5000
```

`data.json`/`data.js` are committed, so the site is populated the moment
Pages is on — it never shows an empty page even before the first scheduled run.

## Configure

- **Add / swap a country or feed:** edit the `COUNTRIES` dict in
  `news_client.py`, then add a matching accent block (`.xx { --accent… }`) in
  `index.html` so the new country gets its own color.
- **Refresh cadence:** change the `cron` in `update-news.yml`.

## Archived Flask app

`legacy_flask/` holds the old Flask server that predated the static site. It
reads the same feeds live (useful as a data preview), but you don't need it to
run the site. To use it: `pip install -r legacy_flask/requirements.txt` then
`python legacy_flask/app.py`.
