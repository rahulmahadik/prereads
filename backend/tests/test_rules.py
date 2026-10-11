from app.engine import apply_rules
from app.models import Book, Readiness, Stop


def stop(role, title, level, conf=0.9, author="A"):
    return Stop(role=role, order=0, book=Book(id=title, title=title, author=author),
                readiness=Readiness(level=level, hours=5), why="w", confidence=conf)


def test_before_must_be_easier_and_confident():
    target = stop("target", "T", 4)
    before = [stop("before", "harder", 5), stop("before", "ok", 2), stop("before", "weak", 3, conf=0.3, author="B")]
    after = [stop("after", "too-easy", 1), stop("after", "deeper", 5, author="C")]
    notes = []
    b, a = apply_rules(target, before, after, notes)
    assert [s.book.title for s in b] == ["ok"]
    assert [s.book.title for s in a] == ["deeper"]
    assert any("not easier" in n for n in notes)


def test_dedupe_same_author_and_cap():
    target = stop("target", "T", 5)
    before = [stop("before", f"b{i}", 1 + i % 3, author=f"auth{i % 2}") for i in range(6)]
    b, _ = apply_rules(target, before, [], [])
    assert len(b) <= 3
    assert len({s.book.author for s in b}) == len(b)
