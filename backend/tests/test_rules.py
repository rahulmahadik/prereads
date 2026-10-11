from app.services.engine import apply_rules
from app.core.models import Book, Readiness, Stop


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


def test_book_cannot_be_both_before_and_after():
    from app.services.engine import apply_rules
    from app.core.models import Book, Readiness, Stop

    def st(role, bid, level):
        return Stop(role=role, order=0, book=Book(id=bid, title=bid, author=f"a-{bid}"), readiness=Readiness(level=level, hours=5), why="", confidence=0.9)

    target = st("target", "T", 4)
    notes: list[str] = []
    before, after = apply_rules(target, [st("before", "X", 3)], [st("after", "X", 3), st("after", "Y", 4)], notes)
    assert [s.book.id for s in before] == ["X"]
    assert [s.book.id for s in after] == ["Y"]
    assert any("already a PreRead" in n for n in notes)


def test_same_title_other_edition_not_repeated():
    from app.services.engine import apply_rules
    from app.core.models import Book, Readiness, Stop

    def st(role, bid, title, level):
        return Stop(role=role, order=0, book=Book(id=bid, title=title, author="Taleb"), readiness=Readiness(level=level, hours=5), why="", confidence=0.9)

    target = st("target", "T", "The Black Swan", 4)
    before, after = apply_rules(target, [], [st("after", "A1", "Antifragile", 4), st("after", "A2", "Antifragile: Things That Gain from Disorder", 4)], [])
    assert [s.book.id for s in after] == ["A1"]


def test_junk_titles_and_subjects_filtered():
    from app.services.discover import clean_category, junk_title

    assert junk_title("Seven Brief Lessons on Physics 8-Copy Counter Display")
    assert not junk_title("Seven Brief Lessons on Physics")
    assert clean_category(["Protected DAISY", "In library", "Physics"], "Catalogue") == "Physics"
    assert clean_category([], "Catalogue") == "Catalogue"


def test_trim_keeps_the_easiest_on_ramp():
    from app.services.engine import apply_rules
    from app.core.models import Book, Readiness, Stop

    def st(bid, level):
        return Stop(role="before", order=0, book=Book(id=bid, title=bid, author=f"a-{bid}"), readiness=Readiness(level=level, hours=5), why="", confidence=0.9)

    target = Stop(role="target", order=0, book=Book(id="T", title="T", author="t"), readiness=Readiness(level=5, hours=40), why="", confidence=1)
    before, _ = apply_rules(target, [st("L1", 1), st("L2", 2), st("L3a", 3), st("L3b", 3), st("L4", 4)], [], [])
    ids = [s.book.id for s in before]
    assert len(ids) == 3 and ids[0] == "L1" and ids[-1] == "L4"
