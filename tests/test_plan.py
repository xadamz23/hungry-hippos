import json
import re
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


def _names_on_list(session):
    return sorted(i.name for i in session.scalars(select(ListItem)))


def test_remove_with_items_takes_the_meals_unchecked_items_off(seeded):
    from app.services import shopping

    ws = planning.current_week()
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef\n8 tortillas\n1 onion")
    chili = make_meal(seeded, "Chili", "1 onion")
    e = planning.add_entry(seeded, ws, None, "meal", tacos.id, add_to_list=True)
    planning.add_entry(seeded, ws, None, "meal", chili.id, add_to_list=True)
    shopping.add_text(seeded, "onion")  # typed by hand: not the meal's
    tortillas = next(i for i in seeded.scalars(select(ListItem)) if i.name == "Tortillas")
    shopping.toggle(seeded, tortillas.id)  # already in the cart
    assert planning.list_items_to_remove(seeded, e) == 2
    assert planning.remove(seeded, e.id, remove_items=True) == 2
    assert _names_on_list(seeded) == ["Onion", "Onion", "Tortillas"]  # chili's, typed, checked


def test_remove_without_items_leaves_the_list(seeded):
    ws = planning.current_week()
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef")
    e = planning.add_entry(seeded, ws, None, "meal", tacos.id, add_to_list=True)
    assert planning.remove(seeded, e.id) == 0
    assert _names_on_list(seeded) == ["Ground beef"]


def test_no_item_offer_when_not_on_the_list_or_planned_again(seeded):
    ws = planning.current_week()
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef")
    chili = make_meal(seeded, "Chili", "1 onion")
    not_added = planning.add_entry(seeded, ws, None, "meal", chili.id)
    assert planning.list_items_to_remove(seeded, not_added) == 0
    first = planning.add_entry(seeded, ws, ws, "meal", tacos.id, add_to_list=True)
    planning.add_entry(seeded, ws, None, "meal", tacos.id, add_to_list=True)  # Tacos twice share one set of rows
    assert planning.list_items_to_remove(seeded, first) == 0
    assert planning.remove(seeded, first.id, remove_items=True) == 0
    assert _names_on_list(seeded) == ["Ground beef"]


def test_entry_sheet_offers_to_remove_items(client, seeded):
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef\n8 tortillas")
    e = planning.add_entry(seeded, planning.current_week(), None, "meal", tacos.id, add_to_list=True)
    html = client.get(f"/plan/entries/{e.id}/sheet").text
    assert "also take its 2 items off the list" in html and 'name="remove_items"' in html
    r = client.post(f"/plan/entries/{e.id}/delete", data={"remove_items": "1"})
    assert "Removed Tacos from the plan and 2 items from the list" in r.headers["HX-Trigger"]
    assert _names_on_list(seeded) == []


def test_entry_sheet_without_items_has_no_offer(client, seeded):
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef")
    e = planning.add_entry(seeded, planning.current_week(), None, "meal", tacos.id)
    assert 'name="remove_items"' not in client.get(f"/plan/entries/{e.id}/sheet").text


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


def test_plan_page_empty_week_shows_days(client):
    html = client.get("/plan?week=2026-10-26").text
    assert html.count("+ Add a meal") == 8  # seven days plus "Not on a day yet"
    assert "Same as last week?" not in html  # nothing to copy
    assert "Everything planned this week is on the list" not in html


def test_plan_page_empty_week_offers_copy(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    planning.add_entry(seeded, MON, WED, "meal", tacos.id)
    planning.add_entry(seeded, MON, None, "eat_out")
    html = client.get("/plan?week=2026-11-02").text
    assert "Copy its 2 meals onto the same days" in html
    assert "Same as last week?" not in client.get("/plan?week=2026-10-26").text  # this week isn't empty


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


def test_pick_row_tap_shows_plan_with_undo(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    r = client.post("/plan/entries", data={"meal_id": tacos.id, "week": "2026-10-26", "day": "2026-10-28", "next": "pick"},
                    headers={"HX-Request": "true"})
    entry = seeded.scalar(select(PlanEntry))
    assert r.status_code == 200 and "<h1>Plan</h1>" in r.text and "Tacos" in r.text
    assert r.headers["HX-Push-Url"] == "/plan?week=2026-10-26"
    toast = json.loads(r.headers["HX-Trigger-After-Settle"])["toast"]
    assert toast["message"].startswith("Planned Tacos for ")
    assert toast["undo"] == f"/plan/entries/{entry.id}/delete"
    client.post(toast["undo"])
    assert seeded.scalar(select(PlanEntry)) is None


def test_pick_sheet_adds_to_the_chosen_day(client, seeded):
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef\n2 limes")
    html = client.get(f"/meals/{tacos.id}/pick-sheet?pick=2026-10-28&week=2026-10-26").text
    assert "Ground beef" in html and "Limes" in html
    assert "Add to Wednesday" in html and 'name="day" value="2026-10-28"' in html and 'value="pick"' in html


def test_pick_sheet_without_a_day(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    html = client.get(f"/meals/{tacos.id}/pick-sheet?pick=none&week=2026-10-26").text
    assert "Add to this week" in html and 'name="day" value=""' in html


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


def test_copy_last_twice_copies_once(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    planning.add_entry(seeded, MON, WED, "meal", tacos.id)
    client.post("/plan/copy-last?week=2026-11-02")
    r = client.post("/plan/copy-last?week=2026-11-02")
    assert "already has meals" in r.headers["HX-Trigger"]
    assert len(seeded.scalars(select(PlanEntry).where(PlanEntry.week_start == date(2026, 11, 2))).all()) == 1


def test_copy_last_button_disables_while_sending(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    planning.add_entry(seeded, MON, WED, "meal", tacos.id)
    assert 'hx-disabled-elt="find button"' in client.get("/plan?week=2026-11-02").text


def test_finish_cooking_marks_todays_plan_entry(seeded):
    on = date(2026, 10, 28)
    tacos = make_meal(seeded, "Tacos", "x")
    earlier = planning.add_entry(seeded, MON, MON, "meal", tacos.id)
    todays = planning.add_entry(seeded, MON, on, "meal", tacos.id)
    log = planning.finish_cooking(seeded, tacos.id, on)
    assert log.plan_entry_id == todays.id and todays.cooked_on == on and earlier.cooked_on is None
    assert planning.finish_cooking(seeded, tacos.id, on) is None  # finishing twice logs once
    planning.undo_cooked(seeded, log.id)
    assert todays.cooked_on is None and seeded.scalars(select(CookLog)).all() == []


def test_finish_cooking_without_a_plan_entry_logs_it_alone(seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    cooked = planning.add_entry(seeded, MON, MON, "meal", tacos.id)
    planning.mark_cooked(seeded, cooked.id, MON)
    planning.add_entry(seeded, date(2026, 11, 2), None, "meal", tacos.id)  # next week's doesn't count
    log = planning.finish_cooking(seeded, tacos.id, WED)
    assert log.plan_entry_id is None
    assert meal_svc.stats_for(seeded, tacos.id) == (WED, 2)


def test_finish_route_shows_the_meal_with_undo(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x")
    entry = planning.add_entry(seeded, planning.current_week(), None, "meal", tacos.id)
    r = client.post(f"/meals/{tacos.id}/finish", headers={"HX-Request": "true"})
    assert r.status_code == 200 and "Made 1 time" in r.text and r.headers["HX-Push-Url"] == f"/meals/{tacos.id}"
    toast = json.loads(r.headers["HX-Trigger-After-Settle"])["toast"]
    assert toast["message"] == "Marked Tacos as cooked"
    seeded.refresh(entry)
    assert entry.cooked_on is not None
    again = client.post(f"/meals/{tacos.id}/finish", headers={"HX-Request": "true"})
    assert json.loads(again.headers["HX-Trigger-After-Settle"])["toast"] == "Already marked as cooked today"
    undo = client.post(toast["undo"])
    assert undo.status_code == 204 and undo.headers["HX-Refresh"] == "true"
    seeded.refresh(entry)
    assert entry.cooked_on is None and seeded.scalars(select(CookLog)).all() == []


def test_cook_page_finish_posts(client, seeded):
    tacos = make_meal(seeded, "Tacos", "x", steps_text="Brown the beef\nServe")
    assert f'action="/meals/{tacos.id}/finish"' in client.get(f"/meals/{tacos.id}/cook").text
    plain = make_meal(seeded, "Toast", "bread")
    assert f'action="/meals/{plain.id}/finish"' in client.get(f"/meals/{plain.id}/cook").text


def test_week_review_lists_pending_meals_and_skips_what_is_on_the_list(client, seeded):
    from app.services import shopping

    ws = planning.current_week()
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef\n1 onion")
    chili = make_meal(seeded, "Chili", "2 cans beans")
    planning.add_entry(seeded, ws, None, "meal", tacos.id)
    planning.add_entry(seeded, ws, None, "meal", chili.id, add_to_list=True)  # already added: not in the review
    shopping.add_text(seeded, "onion")  # typed in: Tacos still needs its own, so it stays ticked with a note
    html = client.get("/plan/to-list/review").text
    assert "Ground beef" in html and "Beans" not in html
    onion = next(i for i in tacos.ingredients if i.name_key == "onion")
    assert f'value="{onion.id}" checked' in html and "Also on the list" in html


def test_review_unticks_what_this_meal_already_has_on_the_list(client, seeded):
    from app.services import shopping

    tacos = make_meal(seeded, "Tacos", "1 lb ground beef\n1 onion")
    chili = make_meal(seeded, "Chili", "1 onion")
    shopping.add_meal(seeded, chili)
    beef = next(i for i in tacos.ingredients if i.name_key == "ground beef")
    shopping.add_meal(seeded, tacos, only={beef.id})
    html = client.get(f"/meals/{tacos.id}/to-list/review").text
    onion = next(i for i in tacos.ingredients if i.name_key == "onion")
    assert re.search(rf'value="{beef.id}"\s*>', html) and "Already on the list" in html  # Tacos' own: unticked
    assert f'value="{onion.id}" checked' in html  # Chili's onion doesn't cover Tacos


def test_week_add_only_ticked_ingredients(client, seeded):
    ws = planning.current_week()
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef\n1 cup rice")
    e = planning.add_entry(seeded, ws, None, "meal", tacos.id)
    beef = next(i for i in tacos.ingredients if i.name_key == "ground beef")
    r = client.post("/plan/to-list", data={"reviewed": "1", "ing": [beef.id]})
    assert "Added ingredients for 1 meal" in r.headers["HX-Trigger"]
    assert _names_on_list(seeded) == ["Ground beef"]
    seeded.refresh(e)
    assert e.added_to_list


def test_week_add_with_nothing_ticked_still_marks_meals_added(client, seeded):
    ws = planning.current_week()
    tacos = make_meal(seeded, "Tacos", "1 cup rice")
    e = planning.add_entry(seeded, ws, None, "meal", tacos.id)
    r = client.post("/plan/to-list", data={"reviewed": "1"})
    assert "Nothing to buy for 1 meal" in r.headers["HX-Trigger"]
    assert _names_on_list(seeded) == []
    seeded.refresh(e)
    assert e.added_to_list


def test_week_review_with_nothing_pending(client, seeded):
    r = client.get("/plan/to-list/review")
    assert r.status_code == 204 and "Nothing new to add" in r.headers["HX-Trigger"]


def test_week_review_from_the_list_targets_the_list(client, seeded):
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef")
    planning.add_entry(seeded, planning.current_week(), None, "meal", tacos.id)
    html = client.get("/plan/to-list/review?target=list").text
    assert 'hx-target="#list-body"' in html
