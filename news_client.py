"""Fetch top headlines for Morocco and the Netherlands from public RSS feeds.

No API key needed — we pull each country's news from a couple of well-known
news sites' RSS/Atom feeds, merge them, and keep the freshest items. A single
feed going down never blanks a country: we take whatever the working feeds
give us, and only surface an error if every feed for every country fails
(e.g. no network).
"""

import html
import re
import time
from dataclasses import dataclass, field

import feedparser
import requests

# Feed sites expect a browser-ish client; a bare python-requests UA gets 403s.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}

# (display name of the outlet, feed URL) per country. Order of the dict sets
# the page order; keep it in sync with the .ma / .nl accent classes in the template.
COUNTRIES = {
    "ma": {
        "name": "Morocco",
        "flag": "🇲🇦",
        "feeds": [
            ("TelQuel", "https://telquel.ma/feed/"),
            ("Hespress", "https://hespress.com/rss/"),
        ],
    },
    "nl": {
        "name": "Netherlands",
        "flag": "🇳🇱",
        "feeds": [
            ("NU.nl", "https://www.nu.nl/rss"),
            ("de Telegraaf", "https://www.telegraaf.nl/rss/index.xml"),
        ],
    },
}

# Strip HTML markup and collapse whitespace so the summarizer sees plain text.
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# WordPress feeds append boilerplate that would otherwise pollute the summary:
# "... The post <title> appeared first on <site>." and a trailing "Read more".
# The real article text here is French/Arabic/Dutch, so these English phrases
# are unambiguous. The full "The post …" form is tried first, then a fallback
# for themes that omit the leading "The post".
_TRAILERS = (
    re.compile(r"\s*the post\b.*?appeared first on.*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"\s*appeared first on.*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"\s*(?:read more|lees meer|lire la suite)[\s.]*$", re.IGNORECASE),
)


def _strip_html(value: str) -> str:
    text = _TAG_RE.sub(" ", value or "")
    text = html.unescape(text)
    for trailer in _TRAILERS:
        text = trailer.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


class NewsFetchError(RuntimeError):
    """Raised when news could not be fetched (all feeds for a country failed)."""


@dataclass
class Article:
    title: str
    source: str
    url: str
    published_at: str
    description: str = ""
    content: str = ""

    @property
    def text(self) -> str:
        """Best available body text for summarization."""
        return (self.content or self.description).strip()


@dataclass
class CountryNews:
    code: str
    name: str
    flag: str
    articles: list[Article] = field(default_factory=list)
    briefing: str = ""


def _parse_feed(url: str, source: str) -> list[Article]:
    """Fetch and parse one feed into Article objects. Raises on failure."""
    resp = requests.get(url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()

    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise NewsFetchError(
            f"feed {source} returned data that could not be parsed as RSS/Atom"
        )

    articles = []
    for entry in feed.entries:
        title = _strip_html(entry.get("title", ""))
        if not title:
            continue
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        published_at = time.strftime("%Y-%m-%d %H:%M", published) if published else ""
        content = entry.get("content") or [{}]
        articles.append(
            Article(
                title=title,
                source=source,
                url=entry.get("link") or "#",
                published_at=published_at,
                description=_strip_html(entry.get("summary", "")),
                content=_strip_html(content[0].get("value", "")),
            )
        )
    return articles


def fetch_country_news(code: str, page_size: int = 30) -> CountryNews:
    """Merge a country's feeds into its freshest `page_size` articles.

    Feeds that fail (timeout, 4xx/5xx, unparseable) are skipped with a note;
    the country still returns whatever the working feeds produced. Raises
    NewsFetchError only if every feed for the country fails.
    """
    meta = COUNTRIES[code]
    seen: set[str] = set()
    merged: list[Article] = []
    ok = 0
    problems: list[str] = []

    for source, url in meta["feeds"]:
        try:
            articles = _parse_feed(url, source)
            ok += 1
        except (requests.RequestException, NewsFetchError) as exc:
            problems.append(f"{source} ({exc.__class__.__name__}: {exc})")
            continue
        for article in articles:
            if article.url in seen:
                continue
            seen.add(article.url)
            merged.append(article)

    if ok == 0:
        raise NewsFetchError(
            f"All feeds failed for {meta['name']}: " + "; ".join(problems)
        )

    # Fixed-width "YYYY-MM-DD HH:MM" sorts correctly as a plain string.
    merged.sort(key=lambda a: a.published_at, reverse=True)
    return CountryNews(
        code=code, name=meta["name"], flag=meta["flag"], articles=merged[:page_size]
    )


def fetch_all_news() -> list[CountryNews]:
    """Return one CountryNews per country.

    A country whose feeds all fail is still included (with no articles) so the
    page can render the rest; we only raise if nothing anywhere could be fetched.
    """
    results: list[CountryNews] = []
    errors: list[str] = []
    for code, meta in COUNTRIES.items():
        try:
            results.append(fetch_country_news(code))
        except NewsFetchError as exc:
            errors.append(str(exc))
            results.append(CountryNews(code=code, name=meta["name"], flag=meta["flag"]))

    if len(errors) == len(COUNTRIES):
        raise NewsFetchError("Could not fetch any news: " + " | ".join(errors))
    return results
