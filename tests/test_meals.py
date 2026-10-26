from datetime import date

from sqlalchemy import select

from app.models import CookLog, Ingredient, ListItem, Meal, PlanEntry
from app.services import meals
from tests.factories import make_meal, section


def test_create_meal_parses_ingredients(seeded):
    meal = make_meal(seeded, "Chili", "2 lb ground beef\n1 yellow onion, diced\n\n2 cans black beans")
    assert [i.name for i in meal.ingredients] == ["ground beef", "yellow onion", "black beans"]
    assert meal.ingredients[2].amounts == [{"qty": 2, "unit": "can"}]
    assert meal.ingredients[0].section.name == "Meat & Seafood"


def test_edit_meal_replaces_ingredients(seeded):
    meal = make_meal(seeded, "Chili", "2 lb ground beef")
    make_meal(seeded, "Chili v2", "1 lb ground turkey", meal=meal)
    assert seeded.scalars(select(Ingredient)).all()[0].name == "ground turkey"
    assert len(seeded.scalars(select(Meal)).all()) == 1


def test_tags_are_reused_case_insensitively(seeded):
    a = make_meal(seeded, "A", "x", tags=["Crockpot"])
    b = make_meal(seeded, "B", "y", tags=["crockpot", " "])
    assert a.tags[0].id == b.tags[0].id


def test_section_override_learns(seeded):
    bakery = section(seeded, "Bakery")
    meal = make_meal(seeded, "Tacos", "1 pack flour tortillas", section_overrides={0: bakery.id})
    assert meal.ingredients[0].section_id == bakery.id
    other = make_meal(seeded, "Wraps", "2 flour tortillas")
    assert other.ingredients[0].section_id == bakery.id


def test_search_by_ingredient(seeded):
    make_meal(seeded, "Tacos", "1 lb ground beef")
    make_meal(seeded, "Pancakes", "2 cups flour")
    rows = meals.search(seeded, q="beef")
    assert [r.meal.name for r in rows] == ["Tacos"]
    assert [r.meal.name for r in meals.search(seeded, q="panc")] == ["Pancakes"]


def test_favorites_filter(seeded):
    make_meal(seeded, "Tacos", "x", favorite=True)
    make_meal(seeded, "Liver", "y")
    assert [r.meal.name for r in meals.search(seeded, favorites=True)] == ["Tacos"]


def test_tag_filter(seeded):
    make_meal(seeded, "Chili", "x", tags=["Crockpot"])
    make_meal(seeded, "Salad", "y")
    assert [r.meal.name for r in meals.search(seeded, tag="Crockpot")] == ["Chili"]


def test_last_made_and_times(seeded):
    meal = make_meal(seeded, "Tacos", "x")
    seeded.add_all([CookLog(meal_id=meal.id, cooked_on=date(2026, 10, 1)), CookLog(meal_id=meal.id, cooked_on=date(2026, 10, 20))])
    seeded.commit()
    row = meals.search(seeded)[0]
    assert row.last_made == date(2026, 10, 20)
    assert row.times_made == 2


def test_pick_mode_order(seeded):
    old_fav = make_meal(seeded, "Alfredo", "x", favorite=True)
    new_fav = make_meal(seeded, "Tacos", "x", favorite=True)
    make_meal(seeded, "Never fav", "x", favorite=True)
    make_meal(seeded, "Zucchini", "x")
    seeded.add_all([CookLog(meal_id=old_fav.id, cooked_on=date(2026, 9, 1)), CookLog(meal_id=new_fav.id, cooked_on=date(2026, 10, 20))])
    seeded.commit()
    names = [r.meal.name for r in meals.search(seeded, pick_mode=True)]
    assert names == ["Never fav", "Alfredo", "Tacos", "Zucchini"]


def test_ingredients_for_step(seeded):
    meal = make_meal(seeded, "Chili", "1 lb ground beef\n1 yellow onion\n2 cans black beans")
    uses = meals.ingredients_for_step(meal, "Brown the ground beef with the onions.", 1.5)
    assert uses == [("Ground beef", "1½ lb"), ("Yellow onion", "1½")]


def test_meals_index_route(client, seeded):
    make_meal(seeded, "Tacos", "1 lb ground beef", favorite=True)
    html = client.get("/meals").text
    assert "Tacos" in html and "Never made" in html


def test_meals_index_empty_state(client):
    assert "No meals yet" in client.get("/meals").text


def test_create_meal_route(client, seeded):
    r = client.post("/meals", data={"name": "Chili", "ingredients": "2 lb ground beef", "steps": "Brown it", "notes": "",
                                    "tags": "Crockpot, Freezer", "servings": "4", "total_minutes": "", "favorite": "1"},
                    follow_redirects=False)
    assert r.status_code == 303
    meal = seeded.scalar(select(Meal))
    assert r.headers["location"] == f"/meals/{meal.id}"
    assert meal.favorite and [t.name for t in meal.tags] == ["Crockpot", "Freezer"] and meal.total_minutes is None


def test_create_meal_requires_name(client, seeded):
    r = client.post("/meals", data={"name": " ", "ingredients": "x"})
    assert r.status_code == 200
    assert "Give the meal a name" in r.text
    assert seeded.scalar(select(Meal)) is None


def test_detail_route(client, seeded):
    meal = make_meal(seeded, "Tacos", "1 lb ground beef", notes="Cheese on the side", steps_text="Brown beef\nServe")
    html = client.get(f"/meals/{meal.id}").text
    assert "Cheese on the side" in html and "Brown beef" in html and "1 lb" in html


def test_detail_404(client):
    assert client.get("/meals/999").status_code == 404


def test_favorite_toggle_route(client, seeded):
    meal = make_meal(seeded, "Tacos", "x")
    r = client.post(f"/meals/{meal.id}/favorite")
    assert 'aria-pressed="true"' in r.text
    seeded.expire_all()
    assert seeded.get(Meal, meal.id).favorite


def test_to_list_route(client, seeded):
    meal = make_meal(seeded, "Tacos", "1 lb ground beef\n1 onion")
    r = client.post(f"/meals/{meal.id}/to-list")
    assert "Added 2 items" in r.headers["HX-Trigger"]
    assert len(seeded.scalars(select(ListItem)).all()) == 2


def test_cook_scales(client, seeded):
    meal = make_meal(seeded, "Tacos", "1 lb ground beef", steps_text="Brown the ground beef.\nServe.", servings=4)
    html = client.get(f"/meals/{meal.id}/cook?servings=6").text
    assert "1½ lb" in html
    assert "Brown the ground beef." in html


def test_delete_meal_on_plan(client, seeded):
    meal = make_meal(seeded, "Tacos", "x")
    seeded.add(PlanEntry(week_start=date(2026, 10, 26), day=date(2026, 10, 27), kind="meal", meal_id=meal.id))
    seeded.commit()
    r = client.post(f"/meals/{meal.id}/delete", follow_redirects=False)
    assert r.status_code == 303
    seeded.expire_all()
    assert seeded.scalars(select(PlanEntry)).all() == []


def test_edit_form_prefilled(client, seeded):
    meal = make_meal(seeded, "Tacos", "1 lb ground beef", tags=["Quick"])
    html = client.get(f"/meals/{meal.id}/edit").text
    assert "1 lb ground beef" in html and 'value="Tacos"' in html and "Quick" in html


