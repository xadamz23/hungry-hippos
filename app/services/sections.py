"""Decide which store section an item belongs in: learned mapping, then keywords, then Other."""

from functools import cache

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import ItemSectionMap, Section
from app.services.ingredients import name_key

OTHER = "Other"

KEYWORDS: dict[str, list[str]] = {
    "Produce": [
        "onion", "garlic", "cilantro", "parsley", "basil", "mint", "dill", "rosemary", "thyme", "scallion",
        "green onion", "shallot", "ginger", "pepper", "bell pepper", "jalapeno", "lettuce", "romaine",
        "spinach", "kale", "arugula", "cabbage", "broccoli", "cauliflower", "carrot", "celery", "cucumber",
        "zucchini", "squash", "potato", "sweet potato", "tomato", "cherry tomato", "avocado", "lime", "lemon",
        "orange", "apple", "banana", "berry", "strawberry", "blueberry", "raspberry", "grape", "pear",
        "peach", "mango", "pineapple", "melon", "watermelon", "mushroom", "corn on the cob", "asparagus",
        "green bean", "brussels sprout", "radish", "beet", "salad mix", "coleslaw mix", "herb",
    ],
    "Bakery": ["bread", "bun", "roll", "bagel", "baguette", "croissant", "english muffin", "pita", "naan",
               "hamburger bun", "hot dog bun", "dinner roll", "sub roll", "muffin"],
    "Deli": ["deli", "parmesan", "rotisserie chicken", "sliced turkey", "sliced ham", "salami", "pepperoni",
             "prosciutto", "hummus", "fresh mozzarella", "provolone"],
    "Meat & Seafood": [
        "beef", "ground beef", "steak", "chicken", "chicken breast", "chicken thigh", "pork", "pork chop",
        "pork loin", "sausage", "italian sausage", "kielbasa", "bacon", "ham", "turkey", "ground turkey",
        "shrimp", "salmon", "tilapia", "cod", "fish", "meatball", "brisket", "roast", "rib", "hot dog",
        "bratwurst", "lamb",
    ],
    "Canned & Soup": [
        "broth", "stock", "chicken broth", "beef broth", "soup", "tomato sauce", "tomato paste",
        "diced tomato", "crushed tomato", "canned", "black bean", "kidney bean", "pinto bean",
        "chickpea", "garbanzo", "refried bean", "baked bean", "corn", "canned corn", "tuna",
        "cream of mushroom", "cream of chicken", "chili bean", "green chile",
    ],
    "Pasta & Rice": [
        "pasta", "spaghetti", "fettuccine", "penne", "macaroni", "elbow", "linguine", "lasagna", "rigatoni",
        "egg noodle", "noodle", "rice", "brown rice", "jasmine rice", "quinoa", "couscous", "marinara",
        "pasta sauce", "spaghetti sauce", "alfredo sauce", "mac and cheese",
    ],
    "International": [
        "tortilla", "flour tortilla", "corn tortilla", "taco shell", "taco seasoning", "salsa", "enchilada sauce",
        "soy sauce", "teriyaki", "teriyaki sauce", "hoisin", "sriracha", "coconut milk", "curry", "ramen",
        "rice noodle", "fish sauce", "sesame oil", "chipotle", "tostada",
    ],
    "Baking & Spices": [
        "flour", "all purpose flour", "sugar", "brown sugar", "powdered sugar", "baking soda",
        "baking powder", "yeast", "vanilla", "vanilla extract", "cocoa", "chocolate chip", "salt",
        "black pepper", "salt and pepper", "pepper flake", "red pepper flake", "paprika", "cumin", "chili powder", "oregano", "cinnamon",
        "garlic powder", "onion powder", "italian seasoning", "seasoning", "spice", "nutmeg", "bay leaf",
        "cornstarch", "olive oil", "vegetable oil", "canola oil", "oil", "cooking spray", "vinegar",
        "honey", "breadcrumb", "panko",
    ],
    "Breakfast & Cereal": ["cereal", "oatmeal", "oat", "granola", "pancake mix", "syrup", "maple syrup",
                           "pop tart", "peanut butter", "jelly", "jam", "coffee", "tea"],
    "Snacks & Drinks": ["chip", "tortilla chip", "cracker", "pretzel", "popcorn", "cookie", "juice", "soda",
                        "sparkling water", "water", "gatorade", "fruit snack", "granola bar", "nut", "almond"],
    "Household": ["paper towel", "toilet paper", "napkin", "trash bag", "foil", "aluminum foil", "plastic wrap",
                  "zip bag", "ziploc", "dish soap", "detergent", "sponge", "tissue", "dog food", "cat food"],
    "Dairy & Eggs": [
        "milk", "egg", "butter", "cheese", "cheddar", "shredded cheese", "mozzarella", "monterey jack",
        "colby", "pepper jack", "cream cheese", "sour cream", "yogurt", "greek yogurt", "heavy cream",
        "whipping cream", "half and half", "cream", "cottage cheese", "biscuit", "crescent roll",
    ],
    "Frozen": ["frozen", "ice cream", "frozen pea", "frozen corn", "frozen vegetable", "frozen pizza",
               "tater tot", "french fry", "waffle", "frozen meatball"],
}


@cache
def _keyword_index() -> list[tuple[str, str]]:
    """(keyword_key, section) sorted so longer phrases are tried first."""
    pairs = [(name_key(k), section) for section, words in KEYWORDS.items() for k in words]
    return sorted(pairs, key=lambda p: (-len(p[0].split()), -len(p[0])))


def keyword_section(key: str) -> str:
    if key.startswith("frozen "):
        return "Frozen"
    padded = f" {key} "
    for kw, section in _keyword_index():
        if f" {kw} " in padded:
            return section
    return OTHER


def guess_section(session: Session, key: str) -> Section:
    learned = session.get(ItemSectionMap, key)
    if learned is not None:
        return learned.section
    wanted = keyword_section(key)
    section = session.scalar(select(Section).where(Section.name == wanted))
    if section is None:
        section = session.scalar(select(Section).where(Section.name == OTHER))
    if section is None:
        section = session.scalar(select(Section).order_by(Section.position.desc()).limit(1))
    return section


def remember(session: Session, key: str, section_id: int) -> None:
    if not key:
        return
    stmt = insert(ItemSectionMap).values(name_key=key, section_id=section_id)
    session.execute(stmt.on_conflict_do_update(index_elements=["name_key"], set_={"section_id": section_id}))
    session.expire_all()


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def text_color(hex_color: str) -> str:
    """White or ink, whichever has higher contrast against the given background."""
    lum = _luminance(hex_color)
    ink = _luminance("#10291C")
    white_contrast = 1.05 / (lum + 0.05)
    ink_contrast = (lum + 0.05) / (ink + 0.05)
    return "#fff" if white_contrast >= ink_contrast else "#10291C"
