"""Fill the database with sample meals, a planned week and a list. Run: .venv/bin/python scripts/demo_data.py"""

from datetime import timedelta

from sqlalchemy import select

from app.clock import today
from app.db import SessionLocal
from app.models import CookLog, Meal
from app.seed import ensure_seed
from app.services import planning, shopping
from app.services.meals import save_meal

MEALS = [
    ("Tacos", True, ["30 min"], 4, "Kids want the cheese and sour cream on the side.",
     "1 lb ground beef\n1 pack flour tortillas\n1 packet taco seasoning\n1 cup shredded cheddar\n1 yellow onion, diced\n1 bunch cilantro\nsour cream",
     "Dice the onion and brown it with the ground beef over medium-high heat.\nDrain the fat, stir in the taco seasoning and 2/3 cup water. Simmer 5 minutes.\nWarm the tortillas in a dry pan.\nServe with cheese, sour cream and cilantro on the side.", [6, 20, 34]),
    ("Crockpot chili", True, ["Crockpot", "Freezer"], 6, "",
     "2 lb ground beef\n2 yellow onions, diced\n2 cans black beans\n2 cans diced tomatoes\n1 packet chili seasoning\n1 cup shredded cheddar",
     "Brown the ground beef with the onions. Drain the fat.\nAdd everything to the crockpot.\nCook on low for 6 to 8 hours.", [12, 40]),
    ("Chicken alfredo", True, ["Pasta"], 4, "",
     "1 lb chicken breasts\n12 oz fettuccine\n2 cups heavy cream\n1 cup grated parmesan\n3 cloves garlic, minced\n4 tbsp butter",
     "Cook the fettuccine.\nSear the chicken and slice it.\nMelt the butter with the garlic, add cream and parmesan.\nToss everything together.", [14]),
    ("Breakfast for dinner", True, ["30 min"], 4, "",
     "2 cups pancake mix\n12 eggs\n1 lb bacon\nmaple syrup", "Cook the bacon.\nMake the pancakes.\nScramble the eggs.", [21]),
    ("Sheet-pan sausage", False, ["30 min"], 4, "",
     "1 lb kielbasa\n2 bell peppers\n1 lb baby potatoes\n2 tbsp olive oil", "Chop everything.\nRoast at 425°F for 25 minutes.", [24]),
    ("Teriyaki bowls", False, [], 4, "",
     "1.5 lb chicken thighs\n1 bottle teriyaki sauce\n2 cups jasmine rice\n1 head broccoli", "Cook the rice.\nCook the chicken with the sauce.\nSteam the broccoli and serve in bowls.", []),
    ("Spaghetti & meatballs", True, ["Pasta", "Freezer"], 4, "",
     "1 lb spaghetti\n1 bag frozen meatballs\n1 jar marinara\nparmesan", "Boil the pasta.\nHeat the meatballs in the sauce.\nServe with parmesan.", [33]),
]


def main() -> None:
    with SessionLocal() as s:
        ensure_seed(s)
        if s.scalar(select(Meal.id).limit(1)):
            print("meals already exist; skipping")
            return
        by_name = {}
        for name, fav, tags, serves, notes, ings, steps, cooked_days_ago in MEALS:
            meal = save_meal(s, meal=None, name=name, ingredients_text=ings, steps_text=steps, notes=notes,
                             tags=tags, servings=serves, total_minutes=None, favorite=fav)
            for d in cooked_days_ago:
                s.add(CookLog(meal_id=meal.id, cooked_on=today() - timedelta(days=d)))
            by_name[name] = meal
        s.commit()
        ws = planning.current_week()
        planning.add_entry(s, ws, ws, "meal", by_name["Tacos"].id)
        planning.add_entry(s, ws, ws + timedelta(days=1), "meal", by_name["Crockpot chili"].id)
        planning.add_entry(s, ws, ws + timedelta(days=3), "leftovers")
        planning.add_entry(s, ws, ws + timedelta(days=4), "meal", by_name["Breakfast for dinner"].id)
        planning.add_entry(s, ws, ws + timedelta(days=5), "eat_out")
        planning.add_entry(s, ws, None, "meal", by_name["Sheet-pan sausage"].id)
        planning.add_week_to_list(s, ws)
        shopping.add_text(s, "1 gal milk")
        shopping.add_text(s, "bananas")
        print("demo data added")


if __name__ == "__main__":
    main()
