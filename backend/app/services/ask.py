"""Grounded questions about one reading path (why_before, time_budget, large_print, free).

The model is given only a brief of the cached route, so its answer is grounded in the stops
already on it; with AI off, a template answers from the same data.

Layer: services. Served by api/routes_paths.py (/api/ask).
"""
from __future__ import annotations

import json

from ..core import config
from ..ai import llm
from ..core.models import AskRequest, AskResponse, Route


# Reader-facing words for the brief, so the model doesn't copy "target" or "stop" into answers.
_ROLE = {"before": "PreRead", "target": "your book", "after": "NextRead"}
_WORDING = ('Say "reading path" and "book", never "line", "stop" or "target". '
            'Say "your book" for the book the reader wants.')


def _route_brief(route: Route) -> str:
    rows = []
    for s in route.stops:
        best = max(s.availability, key=lambda a: a.available, default=None)
        where = f"{best.branch} ({best.available} of {best.total} on the shelf)" if best else "no copies listed"
        rows.append({
            "role": _ROLE.get(s.role, s.role), "order": s.order, "id": s.book.id, "title": s.book.title, "author": s.book.author,
            "level": s.readiness.level, "hours": s.readiness.hours, "why": s.why,
            "assumes": s.readiness.assumed_concepts, "where": where, "hot_at": s.demand.hot_branches,
        })
    return json.dumps(rows, ensure_ascii=False)


# Template answers (AI off), in the reader's language. {wk} is the singular/plural week word.
_T = {
    "en": {
        "ready": "You can start {title} today. Nothing needs to come first.",
        "first": "Read {title} first: {why}.",
        "fit": "With {weeks} {wk} at about 5 hours a week, you can read {books} (about {used} hours).",
        "later": " Leave {books} for later.",
        "over": "Your book alone runs past {weeks} {wk} at about 5 hours a week: it needs about {used} hours. Start with {first} and take it at your own pace.",
        "wk": ("week", "weeks"), "your_book": "your book", "and": " and ", "sep": ", ", "q": "{t}",
        "large": "PreReads doesn't show large-print or audiobook editions yet. Ask at the counter of any library, or check the NLB app for audiobooks of each book on your reading path.",
        "help": "You can ask why a book comes first, how long your reading path takes, or about large print.",
    },
    "zh": {
        "ready": "今天就可以开始读{title}，不需要先读别的书。",
        "first": "先读{title}：{why}。",
        "fit": "按每周大约 5 小时计算，{weeks} {wk}内你可以读完{books}（大约 {used} 小时）。",
        "later": "{books}可以以后再读。",
        "over": "按每周大约 5 小时计算，单是你的书就超过 {weeks} {wk}：大约需要 {used} 小时。先从{first}开始，按自己的节奏读。",
        "wk": ("周", "周"), "your_book": "你的书", "and": "和", "sep": "、", "q": "《{t}》",
        "large": "PreReads 暂时还不显示大字版或有声书。请到任何图书馆的服务台询问，或在 NLB 应用里查找路线上每本书的有声书。",
        "help": "你可以问为什么某本书要先读、读完阅读路线需要多久，或者有没有大字版。",
    },
    "ms": {
        "ready": "Anda boleh mula membaca {title} hari ini. Tiada yang perlu dibaca dahulu.",
        "first": "Baca {title} dahulu: {why}.",
        "fit": "Dengan {weeks} {wk} pada kira-kira 5 jam seminggu, anda boleh membaca {books} (kira-kira {used} jam).",
        "later": " Tinggalkan {books} untuk kemudian.",
        "over": "Buku anda sahaja melebihi {weeks} {wk} pada kira-kira 5 jam seminggu: ia memerlukan kira-kira {used} jam. Mulakan dengan {first} dan bacalah mengikut rentak anda sendiri.",
        "wk": ("minggu", "minggu"), "your_book": "buku anda", "and": " dan ", "sep": ", ", "q": "{t}",
        "large": "PreReads belum menunjukkan edisi cetakan besar atau buku audio. Tanya di kaunter mana-mana perpustakaan, atau semak aplikasi NLB untuk buku audio bagi setiap buku dalam laluan bacaan anda.",
        "help": "Anda boleh bertanya mengapa sesebuah buku dibaca dahulu, berapa lama laluan bacaan anda, atau tentang cetakan besar.",
    },
    "ta": {
        "ready": "{title} நூலை இன்றே தொடங்கலாம். முதலில் எதையும் படிக்க வேண்டியதில்லை.",
        "first": "முதலில் {title} படியுங்கள்: {why}.",
        "fit": "வாரத்திற்குச் சுமார் 5 மணி நேரம் என்றால், {weeks} {wk} {books} படிக்கலாம் (சுமார் {used} மணி நேரம்).",
        "later": " {books} பின்னர் படிக்கலாம்.",
        "over": "உங்கள் நூலுக்கு மட்டுமே சுமார் {used} மணி நேரம் தேவை; வாரத்திற்கு 5 மணி நேரம் என்றால் அது {weeks} {wk} மேல் ஆகும். முதலில் {first} படியுங்கள், உங்கள் வேகத்தில் தொடருங்கள்.",
        "wk": ("வாரத்தில்", "வாரங்களில்"), "wk_over": ("வாரத்துக்கு", "வாரங்களுக்கு"),
        "your_book": "உங்கள் நூல்", "and": " மற்றும் ", "sep": ", ", "q": "{t}",
        "large": "PreReads இன்னும் பெரிய எழுத்து அல்லது ஒலிநூல் பதிப்புகளைக் காட்டவில்லை. எந்த நூலகத்தின் கவுண்டரிலும் கேளுங்கள், அல்லது உங்கள் வாசிப்புப் பாதையின் ஒவ்வொரு நூலுக்கும் NLB செயலியில் ஒலிநூலைத் தேடுங்கள்.",
        "help": "ஒரு நூல் ஏன் முதலில் வருகிறது, உங்கள் வாசிப்புப் பாதைக்கு எவ்வளவு நேரம் ஆகும், அல்லது பெரிய எழுத்துப் பதிப்பு பற்றிக் கேட்கலாம்.",
    },
}


def _words(lang: str | None) -> dict:
    return _T.get((lang or "en")[:2].lower(), _T["en"])


def _titles(w: dict, titles: list[str]) -> str:
    """'A', 'A and B', 'A, B and C' in the reader's language."""
    qs = [w["q"].format(t=t) for t in titles]
    return qs[0] if len(qs) == 1 else w["sep"].join(qs[:-1]) + w["and"] + qs[-1]


def _template(route: Route, req: AskRequest) -> AskResponse:
    w = _words(req.lang)
    before = [s for s in route.stops if s.role == "before"]
    target = next(s for s in route.stops if s.role == "target")
    if req.intent == "why_before":
        if not before:
            return AskResponse(answer=w["ready"].format(title=w["q"].format(t=target.book.title)), engine="template")
        lines = [w["first"].format(title=w["q"].format(t=s.book.title), why=s.why.rstrip(".。")) for s in before]
        return AskResponse(answer=" ".join(lines), engine="template")
    if req.intent == "time_budget":
        weeks = max(1, req.weeks or 2)
        budget = weeks * 5.0  # ~5 reading hours a week
        wk = w["wk"][0 if weeks == 1 else 1]
        # Your book always stays on the plan, so its hours are reserved first; PreReads fill what is left, easiest first.
        if target.readiness.hours > budget:
            picked = before[:1] + [target]
            used = sum(s.readiness.hours for s in picked)
            first = w["q"].format(t=before[0].book.title) if before else w["your_book"]
            wk_over = w.get("wk_over", w["wk"])[0 if weeks == 1 else 1]
            msg = w["over"].format(weeks=weeks, wk=wk_over, used=round(target.readiness.hours), first=first)
            return AskResponse(answer=msg, adjusted_stop_ids=[s.book.id for s in picked], engine="template")
        picked, used = [], target.readiness.hours
        for s in before:
            if used + s.readiness.hours <= budget:
                picked.append(s)
                used += s.readiness.hours
        picked.append(target)
        skipped = [s for s in before if s not in picked]
        msg = w["fit"].format(weeks=weeks, wk=wk, books=_titles(w, [s.book.title for s in picked]), used=round(used))
        if skipped:
            msg += w["later"].format(books=_titles(w, [s.book.title for s in skipped]))
        return AskResponse(answer=msg, adjusted_stop_ids=[s.book.id for s in picked], engine="template")
    if req.intent == "large_print":
        return AskResponse(answer=w["large"], engine="template")
    return AskResponse(answer=w["help"], engine="template")


def answer(route: Route, req: AskRequest) -> AskResponse:
    """Model answer when AI is on and it replies, else the template (engine says which)."""
    if config.llm_enabled():
        q = {
            "why_before": "Why do the PreReads come before your book? Mention each by title.",
            "time_budget": f"The reader has {req.weeks or 2} weeks at about 5 hours a week. Which books fit, in order, and which can wait? Your book always stays on the plan.",
            "large_print": "The reader prefers large print or audio. What should they know about this reading path?",
            "free": req.question or "Summarise the reading path.",
        }[req.intent]
        q = f"{q}\n({_WORDING})"
        brief = _route_brief(route)
        text = llm.ask(brief, q, req.lang) if req.lang else llm.ask(brief, q)
        if text:
            return AskResponse(answer=text, engine="llm")
    return _template(route, req)
