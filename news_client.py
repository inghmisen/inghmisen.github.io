"""Fetch and filter the day's stories into topic lanes for the static site.

The site is organized in lanes (see LANES below), in page order:

- AI & models — r/LocalLLaMA top of day AND week (ungated — the subreddit
  is already the curation), HuggingFace trending new model repos via the
  JSON API, HuggingFace blog, Verge AI, HN front page ≥100 points
  (gated feeds use the AI keyword list).
- Utrecht (UToday) — utoday.nl has no RSS of its own, so we ride Google
  News' site-scoped feed and drop the " - UToday" title suffix.
- Morocco — TelQuel + Hespress, everything fresh.
- The Netherlands — general feeds, but only stories that pass the
  "worth knowing" keyword gate; if none do, the lane stays empty by design.
- Iran & Middle East / Ukraine war — world feeds, keyword-gated to the
  conflicts.

Resilient by design: one feed going down never blanks a lane, and a lane
raises only when ALL of its feeds fail.

Legacy `fetch_all_news`/`COUNTRIES` stay at the bottom for the archived
Flask preview in legacy_flask/.
"""

import html
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser
import requests

# Feed sites expect a browser-ish client; a bare python-requests UA gets 403s.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}

# Strip HTML markup and collapse whitespace so titles are plain text.
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# WordPress feeds append boilerplate ("... The post X appeared first on Y",
# "lees meer", "lire la suite"). The real text is FR/AR/NL/EN, so these
# English phrases are unambiguous to cut.
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
    """Raised when a lane's feeds ALL failed."""


@dataclass
class Article:
    title: str
    source: str
    url: str
    published_at: str


# --- keyword gates -------------------------------------------------------
# Matched against lowercased titles. Substring matching, so "russian",
# "Ukrainian" etc. all hit. Deliberately generous: the clustering sorts it
# afterwards; the cost of a false positive is one extra headline.

_UKRAINE_RE = re.compile(
    r"ukrain|kyiv|zelensk|putin|kremlin|russia|moscow|nato|donetsk|kharkiv|"
    r"kursk|kherson|zaporizh|belgorod|russian|war in ukraine",
    re.IGNORECASE,
)
_MIDEAST_RE = re.compile(
    r"gaza|israel|iran|hezbollah|lebanon|houthi|yemen|red sea|hamas|netanyahu|"
    r"khamenei|tehran|irgc|rafah|west bank|idfb?\b|ceasefire|hezbollah|isfahan|"
    r"middle east|gaza city|khan younis|unrwa|hostage",
    re.IGNORECASE,
)
# Dutch: policy, money, war-and-energy spillover — things a resident of NL
# plausibly needs to know, not celebrity/crime filler.
_NL_RE = re.compile(
    r"kabinet|coalitie|formateur|informateur|tweede kamer|eerste kamer|"
    r"minister|premier|regeerakkoord|verkiezing|oorlog|energie|gasprijs|"
    r"stroomprijs|energieprijs|netbeheerder|asiel|azc|vluchteling|migratie|"
    r"inburgering|belasting|zorgpremie|eigen risico|huur|hypotheek|"
    r"nhg|koopprijs|woningmarkt|nibud|koopkracht|inflatie|cbs|recession|"
    r"economisch|recessie|staking|staken|\bcao\b|werkgever|vakbond|aow|pensioen|"
    r"waterschap|waterstand|dijk|stroomuitval|blackout|treinvertraging|\bns\b|"
    r"schiphol|rivm|fraude|toeslagen|gemeente",
    re.IGNORECASE,
)
_AI_RE = re.compile(
    r"\bai\b|\bartificial intelligence\b|llm|llms\b|gpt|chatgpt|claude|gemini|"
    r"llama|mistral|qwen|deepseek|gemma|phi-|olmo|nemotron|grok|granite|"
    r"openai|anthropic|deepmind|meta ai|hugging ?face|mistral ai|moonshot|"
    r"\bmodel(s)?\b|neural|transformer|diffusion|fine-?tun|dataset|"
    r"context window|inference|token(s|izer)?\b|ollama|rag\b|agent(s|ic)?\b|"
    r"reasoning|benchmark|leaderboard|open[- ]source ai|weights|quantiz|"
    r"machine learning|training run|vibe cod|copilot|cursor|sora|midjourney",
    re.IGNORECASE,
)

# --- lanes ---------------------------------------------------------------
# Order defines page order. "keep" filters titles; None keeps everything.
# Reddit's RSS (.rss) works where .json 403s; GitHub's servers sometimes get
# 403 on it too — then the AI lane silently keeps its other three sources.
LANES = [
    {
        "key": "ai",
        "title": "AI & Models",
        "icon": "🤖",
        "cap": 18,
        "keep": _AI_RE,
        "feeds": [
            # Reddit posts are already curated by the subreddit; the keyword
            # gate would drop posts whose titles just say "3B fits on my GPU".
            ("r/LocalLLaMA", "https://www.reddit.com/r/LocalLLaMA/top.rss?t=day&limit=30", {"keep": None}),
            ("r/LocalLLaMA", "https://www.reddit.com/r/LocalLLaMA/top.rss?t=week&limit=25", {"keep": None}),
            # Brand-new model repos (trending, ≤30 days old) — no RSS exists.
            ("HF new models", "", {"keep": None, "type": "hf_trending"}),
            ("HuggingFace", "https://huggingface.co/blog/feed.xml"),
            ("Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
            ("Hacker News", "https://hnrss.org/frontpage?points=100"),
        ],
        # Weights drops are the reason the lane exists; never let chatter evict them.
        "reserve": {"source": "HF new models", "n": 6},
    },
    {
        # utoday.nl publishes no RSS/Atom feed of its own; a Google News
        # site-search feed is the stable substitute (links are Google
        # redirects that land on the UToday article).
        "key": "utoday",
        "title": "Utrecht (UToday)",
        "icon": "📍",
        "cap": 10,
        "keep": None,
        "feeds": [
            (
                "UToday",
                "https://news.google.com/rss/search"
                "?q=site:utoday.nl&hl=nl&gl=NL&ceid=NL:nl&scoring=n",
                {
                    # Google appends " - utoday.nl"/" - UToday" and indexes
                    # tag pages ("Tagged: X") that aren't articles.
                    "strip": r"\s+-\s*(?:utoday\.nl|U-?Today)\.?$",
                    "drop": r"^Tagged: ",
                },
            ),
        ],
    },
    {
        "key": "morocco",
        "title": "Morocco",
        "icon": "🇲🇦",
        "cap": 18,
        "keep": None,
        "feeds": [
            ("TelQuel", "https://telquel.ma/feed/"),
            ("Hespress", "https://hespress.com/rss/"),
        ],
    },
    {
        "key": "netherlands",
        "title": "The Netherlands",
        "icon": "🇳🇱",
        "cap": 8,
        "keep": _NL_RE,
        "empty_note": "Nothing big worth knowing today.",
        "feeds": [
            ("NU.nl", "https://www.nu.nl/rss"),
            ("de Telegraaf", "https://www.telegraaf.nl/rss/index.xml"),
            ("AD", "https://www.ad.nl/rss"),
        ],
    },
    {
        "key": "mideast",
        "title": "Iran & Middle East",
        "icon": "🌍",
        "cap": 12,
        "keep": _MIDEAST_RE,
        "feeds": [
            ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
            ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
            ("Guardian World", "https://www.theguardian.com/world/rss"),
        ],
    },
    {
        "key": "ukraine",
        "title": "Ukraine War",
        "icon": "🇺🇦",
        "cap": 12,
        "keep": _UKRAINE_RE,
        "feeds": [
            ("Kyiv Independent", "https://kyivindependent.com/feed/rss/"),
            ("Ukrainska Pravda", "https://www.pravda.com.ua/rss/"),
            ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
            ("Guardian World", "https://www.theguardian.com/world/rss"),
            ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ],
    },
]


def _parse_feed(
    url: str, source: str, strip: str | None = None, drop: str | None = None
) -> list[Article]:
    """Fetch and parse one feed into Article objects. Raises on failure.

    strip: regex removing an appended suffix from every title (Google News
    tacks " - <site>" on). drop: titles matching this regex are discarded
    (feeds carry junk the source itself doesn't consider articles).
    """
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
        # Aggregators (Google News) append " - <source>" to titles.
        title = re.sub(rf"\s+-\s*{re.escape(source)}\.?$", "", title).strip()
        if strip:
            title = re.sub(strip, "", title).strip()
        if not title or (drop and re.search(drop, title, re.IGNORECASE)):
            continue
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        published_at = time.strftime("%Y-%m-%d %H:%M", published) if published else ""
        articles.append(
            Article(
                title=title,
                source=source,
                url=entry.get("link") or "#",
                published_at=published_at,
            )
        )
    return articles


def _fetch_hf_trending(source: str, max_age_days: int = 30, limit: int = 10) -> list[Article]:
    """Brand-new HuggingFace models by trending score — the "weights dropped"
    signal. There is no RSS for new model repos, so we hit the public JSON
    API directly and keep only repos created within the last month.
    """
    resp = requests.get(
        "https://huggingface.co/api/models",
        params={"sort": "trendingScore", "direction": -1, "limit": 60},
        headers=_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    articles = []
    for m in resp.json():
        model_id = m.get("id")
        created = m.get("createdAt")
        if not model_id or not created:
            continue
        try:
            made = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            continue
        if made < cutoff:
            continue
        articles.append(
            Article(
                title=f"{model_id} · {m.get('likes', 0)} ♥",
                source=source,
                url=f"https://huggingface.co/{model_id}",
                published_at=time.strftime("%Y-%m-%d %H:%M", made.utctimetuple()),
            )
        )
        if len(articles) >= limit:
            break
    if not articles:
        raise NewsFetchError(f"{source}: no fresh trending models returned")
    return articles


def fetch_lane(lane: dict) -> list[Article]:
    """Merge a lane's feeds into its freshest `cap` kept stories.

    Feeds that fail are skipped; raises NewsFetchError only if every feed in
    the lane failed. Titles are deduped by URL, then filtered through the
    keyword gate. A feed's optional third element (dict) can override the
    lane's `keep` or set `type` for non-RSS sources.
    """
    seen: set[str] = set()
    merged: list[Article] = []
    ok = 0
    problems: list[str] = []

    for feed in lane["feeds"]:
        source, url = feed[0], feed[1]
        opts = feed[2] if len(feed) > 2 else {}
        keep = opts.get("keep", lane.get("keep"))
        try:
            if opts.get("type") == "hf_trending":
                articles = _fetch_hf_trending(source)
            else:
                articles = _parse_feed(url, source, opts.get("strip"), opts.get("drop"))
            ok += 1
        except (requests.RequestException, NewsFetchError) as exc:
            problems.append(f"{source} ({exc.__class__.__name__}: {exc})")
            continue
        for article in articles:
            if article.url in seen:
                continue
            seen.add(article.url)
            if keep is not None and not keep.search(article.title):
                continue
            merged.append(article)

    if ok == 0:
        raise NewsFetchError(
            f"All feeds failed for {lane['title']}: " + "; ".join(problems)
        )

    # Fixed-width "YYYY-MM-DD HH:MM" sorts correctly as a plain string.
    by_date = lambda a: a.published_at or "0000-00-00 00:00"
    merged.sort(key=by_date, reverse=True)

    # A lane's "reserve" pins N stories of one source into the cap — model
    # releases are days old by the time anyone reads them, and pure date
    # order would always let same-day chatter push them out.
    reserve = lane.get("reserve")
    if reserve:
        src, n = reserve["source"], reserve["n"]
        pinned = [a for a in merged if a.source == src][:n]
        rest = [a for a in merged if a.source != src][: lane.get("cap", 20) - len(pinned)]
        return sorted(pinned + rest, key=by_date, reverse=True)

    return merged[: lane.get("cap", 20)]


# ---------------------------------------------------------------------------
# Legacy (archived Flask preview in legacy_flask/app.py)
# ---------------------------------------------------------------------------

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


@dataclass
class CountryNews:
    code: str
    name: str
    flag: str
    articles: list[Article] = None

    def __post_init__(self):
        if self.articles is None:
            self.articles = []


def fetch_country_news(code: str, page_size: int = 30) -> CountryNews:
    meta = COUNTRIES[code]
    merged: list[Article] = []
    seen: set[str] = set()
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
    merged.sort(key=lambda a: a.published_at or "0000-00-00 00:00", reverse=True)
    return CountryNews(
        code=code, name=meta["name"], flag=meta["flag"], articles=merged[:page_size]
    )


def fetch_all_news() -> list[CountryNews]:
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
