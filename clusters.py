"""Group related headlines under keyword-derived cluster labels.

No prose is ever generated — a cluster's label is made of words that actually
appear in its own headlines, so nothing can be summarized into nonsense.
Stemming/stopwords are reused from summarizer.py so the multilanguage
handling (NL/FR/EN + Arabic tokens) stays in one place.
"""

import re
from collections import Counter

from summarizer import _STOPWORDS

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Feed noise that recurs across lanes and would make boring cluster labels.
_EXTRA_STOP = {
    "says", "said", "watch", "live", "video", "photos", "photo", "news",
    "world", "why", "how", "what", "when", "after", "before", "over", "with",
    "reports", "report", "new", "year", "years", "day", "days", "today",
    "story", "read", "article", "here", "this", "that", "from", "will",
    "post", "share", "comments", "update", "updates", "opinie", "column",
}
_STOP = _STOPWORDS | _EXTRA_STOP


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _stems(text: str) -> set[str]:
    return {
        w[:-2] if len(w) > 6 else w
        for w in _tokens(text)
        if w not in _STOP and len(w) > 2
    }


def cluster(articles, max_clusters: int = 4, max_per_cluster: int = 5) -> list[dict]:
    """Cluster headline-carrying articles by shared words.

    Returns [{"label": "Russian, strikes", "articles": [...]}] — clusters of
    2+ articles sharing a word, labeled with the words that recur inside the
    cluster (using the original capitalized word forms). Leftovers go under
    "More headlines". If nothing clusters at all, one unlabeled group.
    """
    data = [
        (a, _stems(a.title), _tokens(a.title)) for a in articles
    ]
    freq: Counter = Counter()
    for _, stems, _ in data:
        freq.update(stems)

    picked: list[dict] = []
    used: set[int] = set()
    for seed, total in freq.most_common(50):
        if total < 2 or len(picked) >= max_clusters:
            break
        idxs = [i for i, (_, stems, _) in enumerate(data) if seed in stems and i not in used]
        if len(idxs) < 2:
            continue
        chosen = idxs[:max_per_cluster]
        used.update(chosen)

        # Label from the stems most shared *within this cluster*, rendered
        # with a real word form seen in the headlines.
        cf: Counter = Counter()
        forms: dict[str, str] = {}
        for i in chosen:
            cf.update(data[i][1])
            for w in data[i][2]:
                key = w[:-2] if len(w) > 6 else w
                forms.setdefault(key, w)
        top = [s for s, n in cf.most_common(6) if n >= 2][:2] or [seed]
        label = " · ".join(dict.fromkeys(forms.get(s, s).capitalize() for s in top))
        picked.append({"label": label, "articles": [data[i][0] for i in chosen]})

    rest = [data[i][0] for i in range(len(data)) if i not in used]
    if picked:
        if rest:
            picked.append({"label": "More headlines", "articles": rest})
        return picked
    return [{"label": "", "articles": list(articles)}]
