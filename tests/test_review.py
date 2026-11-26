from datetime import date

from pipeline.review import ReviewState, apply_result, new_review, select_due

BOXES = [1, 3, 7, 14, 30]
TODAY = date(2026, 11, 26)


def test_new_position_due_tomorrow():
    rs = new_review(TODAY, BOXES)
    assert rs.box == 0 and rs.due == date(2026, 11, 27) and rs.attempts == 0


def test_correct_promotes_and_caps():
    rs = new_review(TODAY, BOXES)
    for expected_box in [1, 2, 3, 4, 4]:
        rs = apply_result(rs, "correct", TODAY, BOXES)
        assert rs.box == expected_box
    assert rs.due == date(2026, 12, 26)
    assert rs.attempts == 5 and rs.lastResult == "correct"


def test_wrong_resets():
    rs = ReviewState(box=3, due=TODAY, attempts=4)
    rs = apply_result(rs, "wrong", TODAY, BOXES)
    assert rs.box == 0 and rs.due == date(2026, 11, 27) and rs.attempts == 5


def test_skipped_stays_and_is_due():
    rs = ReviewState(box=2, due=date(2026, 11, 20), attempts=1)
    rs = apply_result(rs, "skipped", TODAY, BOXES)
    assert rs.box == 2 and rs.due == TODAY and rs.attempts == 1


def test_select_due_orders_overdue_then_drop():
    items = [
        ("a", ReviewState(due=date(2026, 11, 25)), 20.0),
        ("b", ReviewState(due=date(2026, 11, 24)), 10.0),
        ("c", ReviewState(due=date(2026, 11, 25)), 40.0),
        ("d", ReviewState(due=date(2026, 11, 30)), 90.0),  # not due
    ]
    assert select_due(items, TODAY, limit=5) == ["b", "c", "a"]
    assert select_due(items, TODAY, limit=2) == ["b", "c"]
