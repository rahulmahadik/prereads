import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from app.models import Book, Readiness, Route, Stop  # noqa: E402
from eval_paths import check_rules  # noqa: E402


def _stop(role, title, level, author="A", conf=1.0, bid=None):
    return Stop(role=role, order=0, book=Book(id=bid or title, title=title, author=author),
                readiness=Readiness(level=level, hours=5), why="", confidence=conf)


def test_check_rules_flags_before_book_not_easier():
    route = Route(
        target_id="T",
        stops=[_stop("before", "Too Hard", 4, author="X"), _stop("before", "Fine", 2, author="Y"),
               _stop("target", "Target", 3, bid="T")],
        generated_at="now", engine="test")
    out = check_rules(route)
    assert any("Too Hard" in v and "level" in v for v in out)
    assert not any("Fine" in v for v in out)


def test_check_rules_clean_route():
    route = Route(target_id="T", stops=[_stop("before", "Easy", 1), _stop("target", "Target", 3, bid="T")],
                  generated_at="now", engine="test")
    assert check_rules(route) == []
