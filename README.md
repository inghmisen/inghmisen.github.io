# Daily Briefing — AI 🤖, Utrecht 📍, Morocco 🇲🇦, the Netherlands 🇳🇱 & the wars 🌍

A **static** news site that pulls the day's headlines from public RSS feeds
into six topic **lanes** on one clean page — no API key, no database, no
server of your own.

## The lanes

Each lane has its own feed mix and a keyword gate that decides what counts
(in page order):

| Lane | What ships | Gate |
|---|---|---|
| 🤖 AI & Models | r/LocalLLaMA (top of day), HuggingFace blog, Verge AI, HN ≥100 pts | AI/model keywords only |
| 📍 Utrecht (UToday) | utoday.nl via a Google News `site:` feed (it publishes no RSS of its own) | everything UToday runs |
| 🇲🇦 Morocco | TelQuel + Hespress | everything fresh |
| 🇳🇱 The Netherlands | NU.nl, Telegraaf, AD | only policy/money/"worth knowing" stories — an **empty lane is a correct answer** ("Nothing big worth knowing today.") |
| 🌍 Iran & Middle East | Al Jazeera, BBC, Guardian | Gaza/Israel/Iran keywords only |
| 🇺🇦 Ukraine War | Kyiv Independent, Ukrainska Pravda, BBC/Guardian/Al Jazeera world feeds | Ukraine-war keywords only |

Inside a lane, related headlines are grouped into **clusters** labeled with
words that literally appear in their own headlines (`clusters.py`) — nothing
is ever machine-summarized into prose. The header carries a **EUR→MAD** rate
chip with the day's change.

## How it works

There is no backend. A Python script runs on a schedule in GitHub Actions and
refreshes one file, `data.json`; the static page reads it:

```
GitHub cron (every 30 min)
      │  runs
      ▼
generate_data.py ──► news_client.py (RSS lanes + keyword gates)
      │              clusters.py   (keyword-labeled groups)
      │              open.er-api.com (EUR→MAD)
      │  writes, but only if content actually changed
      ▼
   data.json  ── committed & pushed ──► GitHub Pages serves it
      ▲
      │  fetched on load, refetched every 5 min & on tab focus
   index.html (client-side render, no build step)
```

- **`generate_data.py`** — the entry point. Fetches every lane + the FX rate,
  writes `data.json` **and** `data.js` (a JS mirror for the offline case
  below). It *skips the write when nothing changed* (so the cron only commits
  when the news moved), and on a total feed outage it exits non-zero *without*
  overwriting, so the last good data stays published. A single lane whose
  feeds all fail ships as an empty lane with a note — never blanks the page.
- **`news_client.py`** — the `LANES` definition (feeds + keyword gates per
  lane), feed merging, dedupe, freshness cap. One feed going down never blanks
  a lane.
- **`clusters.py`** — groups headlines sharing words and labels clusters from
  those shared words. Labels are extracted, never generated.
- **`index.html`** — the whole front end: lane cards with cluster sections,
  EUR/MAD chip, mobile lane switcher, auto-refresh. No build step, no deps.
- **`data.js`** — a committed `window.__NEWS__ = {…}` snapshot. Browsers block
  `fetch()` on `file://` pages, so this is what lets you **double-click
  `index.html`** and still see the news; over HTTP the page fetches the live
  `data.json` instead.
- **`.github/workflows/update-news.yml`** — the scheduled job that keeps the
  data fresh and pushes it back.
- **`summarizer.py`** + **`legacy_flask/`** — archived Flask preview; the
  static site no longer generates briefing text.

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

- **Add / swap a lane or feed:** edit `LANES` in `news_client.py`
  (`keep` = keyword regex or `None`, `cap` = max stories, `empty_note` for a
  lane allowed to be quiet), then add a matching accent block
  (`.yourkey { --accent… }`) in `index.html` and a short `TAB_LABELS` entry
  for mobile.
- **Tighten what's "worth knowing":** the per-lane `_UKRAINE_RE` / `_MIDEAST_RE`
  / `_NL_RE` / `_AI_RE` regexes in `news_client.py`.
- **Refresh cadence:** change the `cron` in `update-news.yml`.
