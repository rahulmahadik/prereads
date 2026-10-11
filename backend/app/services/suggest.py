"""Example requests for the Home "Try:" row, built from the catalogue we actually hold.

Nothing is hard-coded about books: topics come from the subjects of books on cached
reading paths, titles from the paths' target books, and time budgets from their hours.
Templates exist per UI language; book titles and subjects stay as published.
"""
from __future__ import annotations

import random
from collections import Counter
from datetime import date
from typing import Optional

from ..core.models import Route
from .engine import load_route, seeds

TEMPLATES: dict[str, list[str]] = {
    "en": [
        "I want to understand {topic} but I only have {weeks} weeks",
        "Something simple about {topic} for this weekend",
        "{topic} for a beginner",
        "I want to read {title} — what should I read first?",
        "A gentle introduction to {topic}",
        "{topic} — I've read a bit already",
    ],
    "zh": [
        "我想了解{topic}，但只有{weeks}周时间",
        "这个周末读点关于{topic}的简单书",
        "给初学者的{topic}",
        "我想读《{title}》，应该先读什么？",
        "{topic}入门",
        "{topic}——我已经读过一些",
    ],
    "ms": [
        "Saya mahu faham {topic} tetapi hanya ada {weeks} minggu",
        "Sesuatu yang mudah tentang {topic} untuk hujung minggu ini",
        "{topic} untuk pemula",
        "Saya mahu membaca {title} — apa yang perlu dibaca dahulu?",
        "Pengenalan ringkas tentang {topic}",
        "{topic} — saya sudah membaca sedikit",
    ],
    "ta": [
        "எனக்கு {topic} புரிய வேண்டும், ஆனால் {weeks} வாரங்கள் மட்டுமே உள்ளன",
        "இந்த வார இறுதிக்கு {topic} பற்றி எளிமையான ஒன்று",
        "தொடக்கநிலையாளருக்கான {topic}",
        "நான் {title} படிக்க விரும்புகிறேன் — முதலில் எதைப் படிக்க வேண்டும்?",
        "{topic} பற்றிய எளிய அறிமுகம்",
        "{topic} — ஏற்கெனவே கொஞ்சம் படித்திருக்கிறேன்",
    ],
}

_GENERIC = {"nonfiction", "fiction", "general", "history", "science", "textbooks", "accessible book", "protected daisy", "in library"}


def _topics_and_titles() -> tuple[list[str], list[tuple[str, float]]]:
    """Curated subjects from our target list (librarian-written, readable), and the paths'
    target titles with the hours of PreReads before them."""
    subj: Counter[str] = Counter()
    titles: list[tuple[str, float]] = []
    for s in seeds():
        for x in s.get("subjects", [])[:4]:
            x = x.split("(")[0].strip()
            if 3 <= len(x) <= 28 and len(x.split()) <= 3 and x.isascii() and x.lower() not in _GENERIC:
                subj[x] += 1
        r: Optional[Route] = load_route(s.get("isbn") or s.get("id") or "")
        if r:
            t = next((st for st in r.stops if st.role == "target"), None)
            if t:
                titles.append((s["title"], sum(b.readiness.hours for b in r.stops if b.role == "before")))
    topics = [t for t, _ in subj.most_common(30)]
    return topics, titles


def suggestions(lang: Optional[str] = None, n: int = 4, seed: Optional[int] = None) -> dict:
    """n example requests in the reader's language, rotating daily (or per `seed`)."""
    lang = lang if lang in TEMPLATES else "en"
    topics, titles = _topics_and_titles()
    rng = random.Random(seed if seed is not None else date.today().toordinal())
    out: list[dict] = []
    tpls = TEMPLATES[lang][:]
    rng.shuffle(tpls)
    used: set[str] = set()
    for tpl in tpls:
        if len(out) >= n:
            break
        if "{title}" in tpl:
            if not titles:
                continue
            title, _ = rng.choice(titles)
            if title in used:
                continue
            used.add(title)
            out.append({"text": tpl.format(title=title), "kind": "title", "source": title})
        else:
            if not topics:
                continue
            topic = rng.choice([t for t in topics if t not in used] or topics)
            used.add(topic)
            weeks = rng.choice([2, 3, 4])
            text = tpl.format(topic=topic.lower() if lang == "en" and not topic.isupper() else topic, weeks=weeks)
            out.append({"text": text[0].upper() + text[1:], "kind": "topic", "source": topic})
    return {"suggestions": out, "lang": lang, "from": f"{len(topics)} topics and {len(titles)} reading paths in the catalogue"}
