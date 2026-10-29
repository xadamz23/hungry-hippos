from datetime import date

from sqlalchemy import select

from app.models import CookLog, Ingredient, ListItem, Meal, MealPhoto, PlanEntry, Staple
from app.services import meals
from tests.factories import make_meal, section


def test_create_meal_parses_ingredients(seeded):
    meal = make_meal(seeded, "Chili", "2 lb ground beef\n1 yellow onion, diced\n\n2 cans black beans")
    assert [i.name for i in meal.ingredients] == ["Ground beef", "Yellow onion", "Black beans"]
    assert meal.ingredients[2].amounts == [{"qty": 2, "unit": "can"}]
    assert meal.ingredients[0].section.name == "Meat & Seafood"


def test_edit_meal_replaces_ingredients(seeded):
    meal = make_meal(seeded, "Chili", "2 lb ground beef")
    make_meal(seeded, "Chili v2", "1 lb ground turkey", meal=meal)
    assert seeded.scalars(select(Ingredient)).all()[0].name == "Ground turkey"
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


def test_create_meal_from_ingredient_rows(client, seeded):
    # The form posts one ingredient_lines per row, plus the add box last (often empty)
    r = client.post("/meals", data={"name": "Chili", "ingredient_lines": ["2 lb ground beef", "1 onion", ""]},
                    follow_redirects=False)
    assert r.status_code == 303
    meal = seeded.scalar(select(Meal))
    assert [i.raw for i in meal.ingredients] == ["2 lb ground beef", "1 onion"]


def test_missing_name_keeps_every_ingredient_row(client, seeded):
    r = client.post("/meals", data={"name": " ", "ingredient_lines": ["2 lb ground beef", "1 onion"]})
    assert "Give the meal a name" in r.text
    assert "2 lb ground beef" in r.text and "1 onion" in r.text


def test_meal_form_suggests_staples(client, seeded):
    seeded.add(Staple(name="milk", name_key="milk", amounts=[{"qty": 1, "unit": "gal"}]))
    seeded.commit()
    html = client.get("/meals/new").text
    suggest = html[html.index('id="add-suggest"'):]
    # Picking a staple adds just its name; the amount is set afterwards in the row's sheet
    assert 'data-name="milk"' in suggest and "1 gal" not in suggest
    assert 'data-label="Milk"' in suggest and '<span class="nm">Milk</span>' in suggest
    assert "&#34;lb&#34;" in html  # unit words for splitting amounts off typed lines


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




def test_pick_mode_puts_planned_meals_last(seeded):
    from app.services.planning import add_entry

    a = make_meal(seeded, "Alfredo", "x", favorite=True)
    make_meal(seeded, "Tacos", "x", favorite=True)
    add_entry(seeded, date(2026, 10, 26), None, "meal", a.id)
    names = [r.meal.name for r in meals.search(seeded, pick_mode=True, week_start=date(2026, 10, 26))]
    assert names == ["Tacos", "Alfredo"]


def test_pick_banner_shows_day_name(client, seeded):
    make_meal(seeded, "Tacos", "x")
    html = client.get("/meals?pick=2026-10-28&week=2026-10-26").text
    assert "Choose a meal for Wednesday, Oct 28" in html


def test_planned_on_shows_earliest_day(seeded):
    from app.services.planning import add_entry

    tacos = make_meal(seeded, "Tacos", "x")
    add_entry(seeded, date(2026, 10, 26), date(2026, 10, 26), "meal", tacos.id)
    add_entry(seeded, date(2026, 10, 26), date(2026, 11, 1), "meal", tacos.id)
    add_entry(seeded, date(2026, 10, 26), None, "meal", tacos.id)
    row = meals.search(seeded, week_start=date(2026, 10, 26))[0]
    assert row.planned_on.day == date(2026, 10, 26)


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def test_create_meal_with_photo(client, seeded):
    r = client.post("/meals", data={"name": "Chili", "image_url": ""}, files={"photo": ("photo.jpg", JPEG, "image/jpeg")},
                    follow_redirects=False)
    assert r.status_code == 303
    meal = seeded.scalar(select(Meal))
    photo = seeded.scalar(select(MealPhoto))
    assert meal.image_url == f"/meals/photos/{photo.id}"
    got = client.get(meal.image_url)
    assert got.content == JPEG and got.headers["content-type"] == "image/jpeg"
    assert got.headers["x-content-type-options"] == "nosniff"


def test_photo_must_be_an_image(client, seeded):
    r = client.post("/meals", data={"name": "Chili"}, files={"photo": ("x.jpg", b"<html>hi</html>", "image/jpeg")})
    assert "a photo we can use" in r.text
    assert seeded.scalar(select(Meal)) is None


def test_empty_photo_field_is_ignored(client, seeded):
    r = client.post("/meals", data={"name": "Chili"}, files={"photo": ("", b"", "application/octet-stream")},
                    follow_redirects=False)
    assert r.status_code == 303
    assert seeded.scalar(select(Meal)).image_url is None


def test_new_photo_replaces_the_old_one(client, seeded):
    client.post("/meals", data={"name": "Chili"}, files={"photo": ("a.jpg", JPEG, "image/jpeg")})
    meal = seeded.scalar(select(Meal))
    client.post(f"/meals/{meal.id}", data={"name": "Chili", "image_url": ""}, files={"photo": ("b.jpg", JPEG, "image/jpeg")})
    seeded.expire_all()
    photos = seeded.scalars(select(MealPhoto)).all()
    assert len(photos) == 1 and meal.image_url == f"/meals/photos/{photos[0].id}"


def test_editing_keeps_the_photo(client, seeded):
    client.post("/meals", data={"name": "Chili"}, files={"photo": ("a.jpg", JPEG, "image/jpeg")})
    meal = seeded.scalar(select(Meal))
    url = meal.image_url
    assert f'data-url="{url}"' in client.get(f"/meals/{meal.id}/edit").text
    client.post(f"/meals/{meal.id}", data={"name": "Beef chili", "image_url": url})
    seeded.expire_all()
    assert meal.image_url == url and len(seeded.scalars(select(MealPhoto)).all()) == 1


def test_removing_or_linking_drops_the_uploaded_photo(client, seeded):
    client.post("/meals", data={"name": "Chili"}, files={"photo": ("a.jpg", JPEG, "image/jpeg")})
    meal = seeded.scalar(select(Meal))
    client.post(f"/meals/{meal.id}", data={"name": "Chili", "image_url": "https://example.com/chili.jpg"})
    seeded.expire_all()
    assert meal.image_url == "https://example.com/chili.jpg"
    assert seeded.scalars(select(MealPhoto)).all() == []
    client.post(f"/meals/{meal.id}", data={"name": "Chili", "image_url": ""})
    seeded.expire_all()
    assert meal.image_url is None


def test_deleting_a_meal_deletes_its_photo(client, seeded):
    client.post("/meals", data={"name": "Chili"}, files={"photo": ("a.jpg", JPEG, "image/jpeg")})
    meal = seeded.scalar(select(Meal))
    client.post(f"/meals/{meal.id}/delete")
    assert seeded.scalars(select(MealPhoto)).all() == []


def test_missing_photo_is_404(client):
    assert client.get("/meals/photos/999").status_code == 404


def test_cleared_review_line_does_not_shift_sections(client, seeded):
    from app.models import ItemSectionMap

    deli, frozen = section(seeded, "Deli").id, section(seeded, "Frozen").id
    client.post("/meals", data={"name": "A", "ingredient_lines": ["1 cup parmesan", "", "2 cups peas"],
                                "section_0": deli, "section_2": frozen})
    meal = seeded.scalar(select(Meal))
    assert [(i.name, i.section_id) for i in meal.ingredients] == [("Parmesan", deli), ("Peas", frozen)]
    assert seeded.get(ItemSectionMap, "pea").section_id == frozen


def test_review_line_with_a_line_separator_stays_one_ingredient(client, seeded):
    frozen = section(seeded, "Frozen").id
    client.post("/meals", data={"name": "A", "ingredient_lines": ["heavy cream", "2 cups peas"], "section_1": frozen})
    meal = seeded.scalar(select(Meal))
    assert [(i.raw, i.section_id == frozen) for i in meal.ingredients] == [("heavy cream", False), ("2 cups peas", True)]


def test_unknown_section_override_is_ignored(client, seeded):
    from app.models import ItemSectionMap

    r = client.post("/meals", data={"name": "A", "ingredient_lines": ["2 cups heavy cream"], "section_0": "999999"},
                    follow_redirects=False)
    assert r.status_code == 303
    meal = seeded.scalar(select(Meal))
    assert meal.ingredients[0].section.name == "Dairy & Eggs"
    assert seeded.scalars(select(ItemSectionMap)).all() == []


def test_long_text_is_cut_to_fit(client, seeded):
    r = client.post("/meals", data={"name": "m" * 500, "tags": "t" * 100, "ingredient_lines": ["y" * 500, "1 (" + "z" * 500 + ")"]},
                    follow_redirects=False)
    assert r.status_code == 303
    meal = seeded.scalar(select(Meal))
    assert len(meal.name) == 200 and [len(t.name) for t in meal.tags] == [60]
    assert all(len(i.name) <= 200 and len(i.name_key) <= 200 for i in meal.ingredients)
    client.post(f"/meals/{meal.id}/to-list")
    assert len(seeded.scalars(select(ListItem)).all()) == 2


def test_huge_numbers_are_dropped(client, seeded):
    r = client.post("/meals", data={"name": "A", "servings": "1000000000000", "total_minutes": "99999999999"},
                    follow_redirects=False)
    assert r.status_code == 303
    meal = seeded.scalar(select(Meal))
    assert (meal.servings, meal.total_minutes) == (None, None)


def test_huge_id_is_a_client_error(client, seeded):
    assert client.get("/meals/99999999999").status_code == 400
    seeded.rollback()  # the test client shares one session; in the app each request gets its own
    assert client.post("/list/99999999999/toggle").status_code == 400


def test_failed_save_keeps_the_existing_photo(client, seeded):
    client.post("/meals", data={"name": "Chili"}, files={"photo": ("a.jpg", JPEG, "image/jpeg")})
    meal = seeded.scalar(select(Meal))
    url = meal.image_url
    # A new photo was picked, so the form sends image_url empty, but the name is blank
    r = client.post(f"/meals/{meal.id}", data={"name": " ", "image_url": ""}, files={"photo": ("b.jpg", JPEG, "image/jpeg")})
    assert "Give the meal a name." in r.text and "add it again" in r.text
    assert f'data-url="{url}"' in r.text
    client.post(f"/meals/{meal.id}", data={"name": "Chili", "image_url": url})
    seeded.expire_all()
    assert meal.image_url == url and len(seeded.scalars(select(MealPhoto)).all()) == 1


def test_failed_save_from_review_keeps_the_source_link(client, seeded):
    src = "https://example.com/recipes/alfredo"
    r = client.post("/meals", data={"name": " ", "source_url": src, "image_url": "", "ingredient_lines": ["1 lime"]})
    assert f'name="source_url" value="{src}"' in r.text
    edit = client.get(f"/meals/{make_meal(seeded, 'Tacos').id}/edit").text
    assert 'name="source_url"' not in edit


def test_name_inputs_reject_only_spaces(client, seeded):
    assert r'pattern=".*\S.*"' in client.get("/meals/new").text


def test_cannot_borrow_another_meals_photo(client, seeded):
    client.post("/meals", data={"name": "A"}, files={"photo": ("a.jpg", JPEG, "image/jpeg")})
    client.post("/meals", data={"name": "B"}, files={"photo": ("b.jpg", JPEG, "image/jpeg")})
    a, b = seeded.scalars(select(Meal).order_by(Meal.id)).all()
    a_url, b_url = a.image_url, b.image_url
    client.post(f"/meals/{a.id}", data={"name": "A", "image_url": b_url})
    seeded.expire_all()
    assert a.image_url == a_url
    client.post("/meals", data={"name": "C", "image_url": b_url})
    c = seeded.scalar(select(Meal).where(Meal.name == "C"))
    assert c.image_url is None
    client.post(f"/meals/{b.id}/delete")
    seeded.expire_all()
    assert client.get(a.image_url).status_code == 200
