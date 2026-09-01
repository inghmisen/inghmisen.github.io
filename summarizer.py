"""Dependency-light extractive summarizer (Luhn-style word-frequency scoring).

Works over whatever text the feeds give us (headlines + summaries),
in any language — scoring is by repeated word stems, not language rules.
"""

import re
from collections import Counter

# Sentence boundaries: . ! ? and the Arabic question mark, followed by space.
_SENT_END_RE = re.compile(r"(?<=[.!؟?])\s+")
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Fragments that don't open a real sentence: a digit (number split off by its
# thousands/decimal separator) or punctuation (quote/comma tail).
_TAIL_RE = re.compile(r"^[\d\"'“”‘’«،,\-]")

# Small stopword lists for the languages these feeds produce.
_STOPWORDS = {
    # Dutch
    "de", "het", "een", "van", "in", "is", "op", "te", "en", "dat", "die", "er",
    "aan", "met", "voor", "door", "niet", "ook", "er", "zijn", "heeft", "had",
    "wordt", "werd", "zal", "kan", "nog", "al", "maar", "als", "dan", "over",
    "dit", "deze", "die", "wat", "hoe", "waar", "uit", "na", "bij", "om",
    # French
    "le", "la", "les", "des", "une", "un", "du", "de", "et", "en", "est",
    "dans", "pour", "par", "sur", "avec", "que", "qui", "pas", "plus", "son",
    "ses", "ce", "cette", "au", "aux", "ou", "où", "ne", "se", "être",
    "avoir", "été", "dit", "elle", "il", "ils", "nous", "vous", "tout",
    # English (some feeds are in English)
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "has", "have", "had", "at",
    "by", "from", "as", "it", "its", "that", "this", "but", "not", "say",
    "says", "new",
}


def _sentences(text: str) -> list[str]:
    """Split into sentences without shredding numbers or quotes.

    "1.234" (Dutch thousands) and "0,11" (French/Arabic decimal) must not end
    a sentence, so digit-to-digit separators are shielded before splitting.
    Anything still split off mid-phrase — it starts with a digit or
    punctuation — is the tail of the previous sentence and gets glued back.
    """
    shielded = re.sub(r"(?<=\d)\.(?=\d)", "\x00", text)  # 1.234
    shielded = re.sub(r"(?<=\d),(?=\d)", "\x01", shielded)  # 0,11
    out: list[str] = []
    for frag in _SENT_END_RE.split(shielded):
        # Restore shielded separators.
        frag = frag.strip().replace("\x00", ".").replace("\x01", ",")
        if not frag:
            continue
        if out and _TAIL_RE.match(frag):
            out[-1] = f"{out[-1]} {frag}"
        else:
            out.append(frag)
    return [s for s in out if len(s) > 25]


def _stems(sentence: str) -> list[str]:
    words = _WORD_RE.findall(sentence.lower())
    # Crude stemming: drop plurals/inflections by cutting the last two chars
    # of longer words so "attacks"/"attack" collide.
    return [w[:-2] if len(w) > 6 else w for w in words if w not in _STOPWORDS and len(w) > 2]


def _score(sentence: str, freq: Counter) -> float:
    stems = _stems(sentence)
    if not stems:
        return 0.0
    freq_score = sum(freq[s] for s in stems) / len(stems)
    # Mild bonus for informational length; penalize shouty all-caps fragments.
    length_bonus = min(len(sentence), 180) / 180
    return freq_score * (0.6 + 0.4 * length_bonus)


def _similar(a: str, b: str) -> bool:
    """Near-duplicate check so the briefing doesn't repeat one story."""
    sa, sb = set(_stems(a)), set(_stems(b))
    if not sa or not sb:
        return False
    overlap = len(sa & sb) / min(len(sa), len(sb))
    return overlap > 0.5


def summarize_text(
    text: str, max_sentences: int = 4, titles: list[str] | None = None
) -> str:
    """Pick the most informative, mutually-different sentences from one blob.

    `titles` weight which topics win the scoring (see briefing_for) but are
    never themselves output — they lack sentence punctuation, so quoting them
    verbatim made the briefing read as a shuffled list of headlines.
    """
    sentences = _sentences(text) or _sentences("\n".join(titles or []))
    if not sentences:
        return ""
    freq = Counter(stem for s in sentences for stem in _stems(s))
    for title in titles or []:
        title_stems = _stems(title)
        freq.update(title_stems)
        freq.update(title_stems)  # double weight: titles carry the signal
    ranked = sorted(sentences, key=lambda s: _score(s, freq), reverse=True)

    picked: list[str] = []
    for sentence in ranked:
        if len(picked) >= max_sentences:
            break
        if any(_similar(sentence, p) for p in picked):
            continue
        picked.append(sentence)

    # Restore original reading order.
    picked.sort(key=sentences.index)
    return " ".join(picked)


def briefing_for(articles, max_sentences: int = 5) -> str:
    """A shared daily briefing across a country's articles.

    The prose comes from the article bodies; each headline feeds the keyword
    counts twice — on short feed summaries they carry most of the signal —
    so the briefing reflects what many outlets are covering.
    """
    bodies = "\n".join(a.text for a in articles if a.text)
    titles = [a.title for a in articles]
    return summarize_text(bodies, max_sentences=max_sentences, titles=titles)
