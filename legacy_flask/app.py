"""Flask app: daily news briefing for Morocco and the Netherlands.

ARCHIVED: the site is now static (index.html + data.json updated by
generate_data.py in GitHub Actions). Kept as a live-data preview:
run `python legacy_flask/app.py` from the repo root (pip install flask).
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, render_template

from news_client import CountryNews, NewsFetchError, fetch_all_news
from summarizer import briefing_for

app = Flask(__name__)

CACHE_TTL_SECONDS = 30 * 60  # Don't hammer the feed sites on every visit.
_cache: dict = {"data": None, "error": None, "fetched_at": 0.0, "fetched_at_str": None}


def get_briefing() -> tuple[list[CountryNews] | None, str | None, str | None]:
    """Return (countries, error, fetched_at_str) — cached for CACHE_TTL_SECONDS."""
    now = time.monotonic()
    fresh = _cache["fetched_at"] and now - _cache["fetched_at"] < CACHE_TTL_SECONDS
    if fresh and (_cache["data"] or _cache["error"]):
        return _cache["data"], _cache["error"], _cache["fetched_at_str"]

    try:
        data = fetch_all_news()
        for country in data:
            country.briefing = briefing_for(country.articles)
        _cache.update(data=data, error=None)
    except NewsFetchError as exc:
        # Keep stale data on refresh failure if we have any; otherwise show the error.
        _cache.update(error=str(exc))
    _cache["fetched_at"] = now
    _cache["fetched_at_str"] = time.strftime("%H:%M UTC", time.gmtime())
    return _cache["data"], _cache["error"], _cache["fetched_at_str"]


@app.route("/")
def index():
    data, error, fetched_at = get_briefing()
    now = time.localtime()
    today = f"{time.strftime('%A', now)} {now.tm_mday} {time.strftime('%B', now)} {now.tm_year}"
    return render_template(
        "index.html",
        countries=data or [],
        error=error,
        today=today,
        total_stories=sum(len(c.articles) for c in data) if data else 0,
        fetched_at=fetched_at if not error and data else None,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
