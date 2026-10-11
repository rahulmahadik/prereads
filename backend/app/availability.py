"""Where is each stop on a shelf right now, and where is it in demand?

Live path: NLB GetAvailabilityInfo (per-branch items) and the checkout-trends
endpoint. Fallback: a deterministic demo table derived from the book id so the
UI is stable between runs. Demo rows carry demo=True and the UI labels them.
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict

from .catalog import _pick, nlb
from .models import Availability, Book, Demand

log = logging.getLogger("prereads.availability")

# Branch code -> display name. A representative subset; the live API returns
# whatever branches actually hold the item.
BRANCHES: dict[str, str] = {
    "BIPL": "Bishan Public Library",
    "JWPL": "Jurong West Public Library",
    "TRL": "Tampines Regional Library",
    "WRL": "Woodlands Regional Library",
    "CLPL": "Central Public Library",
    "PRL": "Punggol Regional Library",
    "BBPL": "Bukit Batok Library",
    "AMKPL": "Ang Mo Kio Public Library",
}

# Rough Dewey ranges by subject keyword, used only to make demo call numbers
# look like real NLB call numbers (English <Dewey> <AUTHOR-4>).
_DEWEY_HINTS = [
    (("systems theory", "complexity", "systems thinking"), "003"),
    (("psychology", "decision", "behavio", "cognit", "thinking"), "153.4"),
    (("economics", "capital", "finance", "invest", "money", "wealth"), "332.6"),
    (("evolution", "biology", "gene"), "576.8"),
    (("physics", "cosmology", "time", "universe"), "523.1"),
    (("history", "singapore", "memoir"), "959.57"),
    (("computer", "software", "program", "algorithm", "data"), "005.1"),
    (("machine learning", "deep learning", "artificial"), "006.31"),
    (("philosophy", "stoic", "science", "logic", "mathematics"), "100"),
    (("medicine", "cancer", "sleep", "health", "body"), "613"),
    (("habit", "productivity", "self"), "158.1"),
]


# Real Dewey classes for the seed set (demo mode only; live mode uses NLB's call numbers).
_DEWEY_BY_TITLE: dict[str, str] = {
    "thinking, fast and slow": "153.4", "predictably irrational": "153.83", "the undoing project": "153.4", "nudge": "330.019",
    "noise": "153.83", "superforecasting": "303.49", "judgment under uncertainty": "153.4",
    "gödel, escher, bach": "510.1", "logicomix": "741.5", "gödel's proof": "511.3", "i am a strange loop": "126", "the mind's i": "126", "metamagical themas": "500",
    "sapiens": "909", "a short history of nearly everything": "500", "origin story": "909", "homo deus": "909.83", "guns, germs, and steel": "303.4", "the dawn of everything": "909",
    "the black swan": "155.2", "the drunkard's walk": "519.2", "fooled by randomness": "332.6", "antifragile": "155.24", "the signal and the noise": "519.5",
    "the selfish gene": "576.82", "why evolution is true": "576.8", "the greatest show on earth": "576.8", "the blind watchmaker": "576.8", "the extended phenotype": "575",
    "a brief history of time": "523.1", "astrophysics for people in a hurry": "523.01", "seven brief lessons on physics": "530", "the order of time": "530.11", "the fabric of the cosmos": "523.1", "black holes and time warps": "523.8",
    "the intelligent investor": "332.6", "the little book of common sense investing": "332.63", "one up on wall street": "332.63", "a random walk down wall street": "332.63", "the most important thing": "332.6", "common stocks and uncommon profits": "332.63", "security analysis": "332.6",
    "capital in the twenty-first century": "332.041", "economics: the user's guide": "330", "the undercover economist": "330", "naked economics": "330", "the price of inequality": "339.2", "capital and ideology": "330.9",
    "deep learning": "006.31", "make your own neural network": "006.32", "grokking deep learning": "006.31", "hands-on machine learning with scikit-learn, keras, and tensorflow": "006.31", "reinforcement learning: an introduction": "006.31", "probabilistic machine learning: an introduction": "006.31",
    "designing data-intensive applications": "005.7", "learning sql": "005.75", "database design for mere mortals": "005.74", "web scalability for startup engineers": "005.1", "fundamentals of software architecture": "005.1", "database internals": "005.74",
    "clean architecture": "005.1", "clean code": "005.1", "the pragmatic programmer": "005.1", "patterns of enterprise application architecture": "005.1", "domain-driven design": "005.1",
    "the structure of scientific revolutions": "501", "philosophy of science: a very short introduction": "501", "what is this thing called science?": "501", "the logic of scientific discovery": "501", "against method": "501",
    "meditations": "188", "how to think like a roman emperor": "188", "a guide to the good life": "188", "letters from a stoic": "188", "discourses and selected writings": "188",
    "atomic habits": "158.1", "the power of habit": "158.1", "tiny habits": "158.1", "deep work": "650.1",
    "why we sleep": "612.821", "the circadian code": "612.022", "breath": "612.2",
    "the emperor of all maladies": "616.994", "the immortal life of henrietta lacks": "616.027", "being mortal": "362.175", "the gene": "576.5", "the song of the cell": "571.6",
    "the singapore story": "959.5705", "singapore: a biography": "959.57", "from third world to first": "959.5705", "hard truths to keep singapore going": "959.5705",
    "thinking in systems": "003", "the fifth discipline": "658.4", "limits to growth": "338.9",
    "the code book": "652.8", "serious cryptography": "005.82", "applied cryptography": "005.82",
    "introduction to algorithms": "005.1", "grokking algorithms": "005.1", "algorithms": "005.1", "the algorithm design manual": "005.1", "concrete mathematics": "510", "the art of computer programming, volume 1": "005.1",
    "the phoenix project": "658.4", "the devops handbook": "004.068", "accelerate": "005.1", "site reliability engineering": "004.068",
    "the wealth of nations": "330.15", "the worldly philosophers": "330.1", "adam smith: what he thought, and why it matters": "330.15", "the theory of moral sentiments": "170", "the great transformation": "330.9",
}


def _dewey(book: Book) -> str:
    if book.ddc:
        return book.ddc
    key = book.title.lower().strip()
    if key in _DEWEY_BY_TITLE:
        return _DEWEY_BY_TITLE[key]
    for k, v in _DEWEY_BY_TITLE.items():
        if key.startswith(k) or k.startswith(key):
            return v
    text = " ".join([book.title] + book.subjects).lower()
    for keys, dewey in _DEWEY_HINTS:
        if any(k in text for k in keys):
            return dewey
    return "001.4"


def _author_code(book: Book) -> str:
    surname = (book.author.split(",")[0].split(" ")[-1] if book.author else book.title)[:3]
    return surname.upper() or "BOO"


def demo_availability(book: Book) -> list[Availability]:
    h = int(hashlib.sha256(book.id.encode()).hexdigest(), 16)
    rows: list[Availability] = []
    codes = list(BRANCHES)
    for i, code in enumerate(codes):
        bits = (h >> (i * 6)) & 0x3F
        total = bits % 4            # 0..3 copies held
        if total == 0:
            continue
        available = (bits >> 2) % (total + 1)
        rows.append(
            Availability(
                branch=BRANCHES[code],
                branch_code=code,
                call_number=f"English {_dewey(book)} {_author_code(book)}",
                available=available,
                total=total,
                demo=True,
            )
        )
    return rows


def demo_demand(book: Book, availability: list[Availability]) -> Demand:
    h = int(hashlib.sha256(("demand:" + book.id).encode()).hexdigest(), 16)
    hot = [a.branch for i, a in enumerate(availability) if ((h >> i) & 1) and a.total >= 2][:2]
    all_available = bool(availability) and all(a.available == a.total for a in availability)
    return Demand(hot_branches=hot, hidden_gem=all_available and not hot, demo=True)


def live_availability(book: Book) -> list[Availability]:
    """GetAvailabilityInfo items: {callNumber, formattedCallNumber, location:{code,name},
    status:{name, code}, language, itemId}. Aggregated per branch."""
    items = nlb().availability(brn=book.brn, isbn=book.isbn)
    if not items:
        return []
    per_branch: dict[str, dict] = defaultdict(lambda: {"available": 0, "total": 0, "call": "", "code": ""})
    for it in items:
        loc = _pick(it, "location", default={}) or {}
        branch = str(_pick(loc, "name", default="") if isinstance(loc, dict) else loc or "")
        code = str(_pick(loc, "code", default="") if isinstance(loc, dict) else "")
        if not branch:
            continue
        st = _pick(it, "status", default={}) or {}
        status = str((_pick(st, "name", default="") if isinstance(st, dict) else st) or "").lower()
        row = per_branch[branch]
        row["total"] += 1
        if status.startswith("available") or status in {"in library", "on shelf"}:
            row["available"] += 1
        row["call"] = row["call"] or str(_pick(it, "formattedCallNumber", "callNumber", default="") or "")
        row["code"] = row["code"] or code
    rows = [
        Availability(branch=b, branch_code=v["code"], call_number=v["call"], available=v["available"], total=v["total"])
        for b, v in per_branch.items()
    ]
    rows.sort(key=lambda a: (-a.available, a.branch))
    return rows


def live_demand(book: Book, availability: list[Availability]) -> Demand | None:
    """Hot branches = branches where this title appears in the checkout-trends
    list. Returns None if the trends endpoint is unavailable (then the UI shows
    no demand badge rather than a fake one)."""
    hot: list[str] = []
    try:
        for a in availability[:8]:
            if not a.branch_code:
                continue
            for it in nlb().trends(location=a.branch_code):
                t = str(_pick(it, "title", default="") or "").lower()
                isbns = _pick(it, "isbns", default=[]) or []
                if (book.isbn and book.isbn in [str(x).replace("-", "") for x in isbns]) or (t and book.title.lower()[:30] in t):
                    hot.append(a.branch)
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("demand lookup failed: %s", exc)
        return None
    all_available = bool(availability) and all(a.available == a.total for a in availability)
    return Demand(hot_branches=hot, hidden_gem=all_available and not hot and book.reservations == 0, reservations=book.reservations, demo=False)


def get_availability(book: Book) -> list[Availability]:
    if nlb().enabled():
        rows = live_availability(book)
        if rows:
            return rows
    return demo_availability(book)


def get_demand(book: Book, availability: list[Availability]) -> Demand:
    if nlb().enabled() and availability and not availability[0].demo:
        d = live_demand(book, availability)
        if d is not None:
            return d
        return Demand(demo=False)
    return demo_demand(book, availability)
