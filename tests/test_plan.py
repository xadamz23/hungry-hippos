from datetime import date

from sqlalchemy import select

from app.models import CookLog, ListItem, PlanEntry
from app.services import meals as meal_svc
from app.services import planning
from tests.factories import make_meal

MON = date(2026, 10, 26)
WED = date(2026, 10, 28)


def test_week_start_monday():
    assert planning.week_start(date(2026, 10, 26)) == MON
    assert planning.week_start(date(2026, 11, 1)) == MON
    assert planning.week_start(date(2026, 11, 2)) == date(2026, 11, 2)


def test_add_and_view_week(seeded):
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef")
    chili = make_meal(seeded, "Chili", "2 cans beans")
    planning.add_entry(seeded, MON, WED, "meal", tacos.id)
    planning.add_entry(seeded, MON, None, "meal", chili.id)
    planning.add_entry(seeded, MON, date(2026, 10, 29), "leftovers")
    view = planning.week(seeded, MON)
    assert [d for d, _ in view.days] == [date(2026, 10, 26 + i) for i in range(6)] + [date(2026, 11, 1)]
    wed = dict(view.days)[WED]
    assert [e.meal.name for e in wed] == ["Tacos"]
    assert [e.meal.name for e in view.unscheduled] == ["Chili"]
    assert view.pending_count == 2


def test_add_entry_derives_week_from_day(seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    e = planning.add_entry(seeded, date(2026, 11, 2), date(2026, 11, 4), "meal", tacos.id)
    assert e.week_start == date(2026, 11, 2)


def test_add_entry_with_list(seeded):
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef\n1 onion")
    e = planning.add_entry(seeded, MON, WED, "meal", tacos.id, add_to_list=True)
    assert e.added_to_list
    assert len(seeded.scalars(select(ListItem)).all()) == 2


def test_add_week_to_list_only_pending(seeded):
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef")
    chili = make_meal(seeded, "Chili", "2 lb ground beef")
    planning.add_entry(seeded, MON, WED, "meal", tacos.id)
    planning.add_entry(seeded, MON, None, "meal", chili.id)
    planning.add_entry(seeded, MON, None, "eat_out")
    assert planning.add_week_to_list(seeded, MON) == 2
    assert planning.add_week_to_list(seeded, MON) == 0
    items = seeded.scalars(select(ListItem).order_by(ListItem.id)).all()
    assert [i.amounts for i in items] == [[{"qty": 1, "unit": "lb"}], [{"qty": 2, "unit": "lb"}]]
    assert planning.week(seeded, MON).pending_count == 0


def test_mark_cooked_logs_and_toggles(seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    e = planning.add_entry(seeded, MON, WED, "meal", tacos.id)
    planning.mark_cooked(seeded, e.id, WED)
    assert e.cooked_on == WED
    assert [c.cooked_on for c in seeded.scalars(select(CookLog))] == [WED]
    planning.mark_cooked(seeded, e.id, WED)
    assert e.cooked_on is None
    assert seeded.scalars(select(CookLog)).all() == []


def test_last_made_from_cooklog(seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    e = planning.add_entry(seeded, MON, WED, "meal", tacos.id)
    planning.mark_cooked(seeded, e.id, WED)
    assert meal_svc.stats_for(seeded, tacos.id) == (WED, 1)


def test_move_and_remove(seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    e = planning.add_entry(seeded, MON, WED, "meal", tacos.id)
    planning.move(seeded, e.id, None)
    assert e.day is None and e.week_start == MON
    planning.move(seeded, e.id, date(2026, 11, 3))
    assert e.week_start == date(2026, 11, 2)
    planning.remove(seeded, e.id)
    assert seeded.scalars(select(PlanEntry)).all() == []


def test_copy_last_week(seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    planning.add_entry(seeded, MON, WED, "meal", tacos.id)
    planning.add_entry(seeded, MON, None, "leftovers")
    nxt = date(2026, 11, 2)
    assert planning.copy_week(seeded, MON, nxt) == 2
    view = planning.week(seeded, nxt)
    assert [e.meal.name for e in dict(view.days)[date(2026, 11, 4)]] == ["Tacos"]
    assert [e.kind for e in view.unscheduled] == ["leftovers"]


def test_history_groups_by_week(seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    chili = make_meal(seeded, "Chili", "x")
    seeded.add_all([CookLog(meal_id=tacos.id, cooked_on=date(2026, 10, 26)),
                    CookLog(meal_id=chili.id, cooked_on=date(2026, 10, 22)),
                    CookLog(meal_id=tacos.id, cooked_on=date(2026, 10, 19))])
    seeded.commit()
    groups = planning.history(seeded, on=date(2026, 10, 27))
    assert [label for label, _ in groups] == ["This week", "Last week"]
    assert [(d, m.name, n) for d, m, n in groups[1][1]] == [(date(2026, 10, 22), "Chili", 1), (date(2026, 10, 19), "Tacos", 2)]


def test_plan_page_empty_state(client):
    html = client.get("/plan?week=2026-10-26").text
    assert "Nothing planned yet" in html


def test_plan_page_lists_entries(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x", favorite=True)
    planning.add_entry(seeded, MON, WED, "meal", tacos.id)
    planning.add_entry(seeded, MON, None, "eat_out")
    html = client.get("/plan?week=2026-10-26").text
    assert "Tacos" in html and "Eating out" in html and "Add ingredients for 1 meal" in html


def test_plan_entry_route_from_meal_sheet(client, seeded):
    tacos = make_meal(seeded, "Tacos", "1 lb beef")
    r = client.post("/plan/entries", data={"meal_id": tacos.id, "week": "2026-10-26", "day": "2026-10-28", "add_to_list": "1", "next": "stay"})
    assert r.status_code == 204
    assert "Planned for Wednesday" in r.headers["HX-Trigger"]
    assert len(seeded.scalars(select(ListItem)).all()) == 1


def test_plan_entry_route_from_pick_mode(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    r = client.post("/plan/entries", data={"meal_id": tacos.id, "week": "2026-10-26", "day": ""}, headers={"HX-Request": "true"})
    assert r.headers["HX-Redirect"] == "/plan?week=2026-10-26"
    assert seeded.scalar(select(PlanEntry)).day is None


def test_plan_sheet_shows_taken_days(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    alfredo = make_meal(seeded, "Alfredo", "x")
    planning.add_entry(seeded, planning.current_week(), planning.current_week(), "meal", tacos.id)
    html = client.get(f"/meals/{alfredo.id}/plan").text
    assert "Plan Alfredo" in html and "Tacos" in html


def test_to_list_route_for_list_page(client, seeded):
    tacos = make_meal(seeded, "Tacos", "1 lb beef")
    planning.add_entry(seeded, planning.current_week(), None, "meal", tacos.id)
    r = client.post("/plan/to-list", headers={"HX-Target": "list-body"})
    assert "Beef" in r.text and "Added ingredients for 1 meal" in r.headers["HX-Trigger"]


def test_cooked_route(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    e = planning.add_entry(seeded, MON, WED, "meal", tacos.id)
    r = client.post(f"/plan/entries/{e.id}/cooked")
    assert r.status_code == 200
    assert len(seeded.scalars(select(CookLog)).all()) == 1


def test_copy_last_route(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    planning.add_entry(seeded, MON, WED, "meal", tacos.id)
    client.post("/plan/copy-last?week=2026-11-02")
    assert len(seeded.scalars(select(PlanEntry).where(PlanEntry.week_start == date(2026, 11, 2))).all()) == 1


def test_history_page(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    seeded.add(CookLog(meal_id=tacos.id, cooked_on=date(2026, 10, 20)))
    seeded.commit()
    assert "Tacos" in client.get("/more/history").text


def test_list_page_shows_plan_aside(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    planning.add_entry(seeded, planning.current_week(), None, "meal", tacos.id)
    html = client.get("/list").text
    assert 'id="aside"' in html and "Tacos" in html
