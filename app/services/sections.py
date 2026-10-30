"""Decide which store section an item belongs in: learned mapping, then a matching staple, then keywords,
then Other."""

from functools import cache

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from app.models import ItemSectionMap, Section, Staple
from app.services.ingredients import name_key, parse_line

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
        "rotisserie chicken", "roasted chicken",
    ],
    "Meat & Seafood": [
        "beef", "ground beef", "steak", "chicken", "chicken breast", "chicken thigh", "pork", "pork chop",
        "pork loin", "sausage", "italian sausage", "kielbasa", "bacon", "ham", "turkey", "ground turkey",
        "shrimp", "salmon", "tilapia", "cod", "fish", "meatball", "brisket", "roast", "rib", "hot dog",
        "bratwurst", "lamb",
    ],
    "Bakery": ["croissant", "baguette", "muffin", "donut", "cake", "cupcake"],
    "Deli": ["deli", "sliced turkey", "sliced ham", "salami", "pepperoni", "prosciutto", "hummus", "cheese",
             "cheddar", "mozzarella", "fresh mozzarella", "provolone", "parmesan", "monterey jack", "colby",
             "pepper jack", "american cheese", "shredded cheese", "mashed potato"],
    "Alcohol": ["beer", "wine", "vodka", "rum", "whiskey", "bourbon", "tequila", "gin", "hard seltzer",
                "ginger beer"],
    "Pop & Gatorade": ["pop", "soda", "cola", "coke", "diet coke", "sprite", "pepsi", "root beer", "ginger ale",
                       "gatorade", "juice", "v8", "tea", "green tea"],
    "Pasta & Mexican": [
        "pasta", "spaghetti", "fettuccine", "penne", "macaroni", "elbow", "linguine", "lasagna", "rigatoni",
        "egg noodle", "noodle", "marinara", "pasta sauce", "spaghetti sauce", "alfredo sauce", "mac and cheese",
        "tomato sauce", "tomato paste", "diced tomato", "crushed tomato", "whole tomato",
        "black bean", "kidney bean", "pinto bean", "chickpea", "garbanzo", "refried bean", "baked bean",
        "chili bean", "tortilla", "flour tortilla", "corn tortilla", "taco shell", "taco seasoning",
        "fajita seasoning", "salsa", "enchilada sauce", "chipotle", "tostada", "green chile",
    ],
    "Rice & Asian": [
        "rice", "brown rice", "jasmine rice", "quinoa", "couscous", "soy sauce", "teriyaki", "teriyaki sauce",
        "hoisin", "sriracha", "coconut milk", "curry", "ramen", "rice noodle", "fish sauce", "sesame oil",
        "canned", "corn", "canned corn",
    ],
    "Soup, Oil & Mayo": [
        "broth", "stock", "chicken broth", "beef broth", "soup", "tuna", "cream of mushroom", "cream of chicken",
        "olive oil", "vegetable oil", "canola oil", "avocado oil", "oil", "cooking spray", "vinegar",
        "mayo", "mayonnaise", "dressing", "salad dressing", "ranch", "bbq sauce", "barbecue sauce",
    ],
    "Bread & Condiments": ["bread", "bun", "roll", "bagel", "english muffin", "pita", "naan", "hamburger bun",
                           "hot dog bun", "dinner roll", "sub roll", "hawaiian roll", "ketchup", "mustard",
                           "relish", "pickle", "water", "sparkling water"],
    "Cereal & Peanut Butter": ["cereal", "oatmeal", "oat", "granola", "pancake mix", "syrup", "maple syrup",
                               "pop tart", "peanut butter", "jelly", "jam", "honey", "coffee"],
    "Spices, Baking & Snacks": [
        "flour", "all purpose flour", "sugar", "brown sugar", "powdered sugar", "baking soda",
        "baking powder", "yeast", "vanilla", "vanilla extract", "cocoa", "chocolate chip", "salt",
        "black pepper", "salt and pepper", "pepper flake", "red pepper flake", "paprika", "cumin", "chili powder",
        "oregano", "cinnamon", "garlic powder", "onion powder", "italian seasoning", "seasoning", "spice",
        "nutmeg", "bay leaf", "cornstarch", "breadcrumb", "panko",
        "chip", "tortilla chip", "pretzel", "popcorn", "nut", "almond", "peanut", "granola bar", "fruit snack",
        "cookie",
    ],
    "Dairy & Eggs": ["milk", "egg", "sour cream", "heavy cream", "whipping cream", "half and half", "cream",
                     "cottage cheese", "cream cheese"],
    "Paper & Laundry": ["paper towel", "toilet paper", "napkin", "trash bag", "garbage bag", "foil",
                        "aluminum foil", "plastic wrap", "zip bag", "ziploc", "freezer bag", "sandwich bag",
                        "paper plate", "tissue", "detergent", "laundry detergent", "dryer sheet"],
    "Yogurt, Butter & Ritz": ["yogurt", "greek yogurt", "butter", "ritz", "cracker", "pie crust", "hashbrown",
                              "orange juice", "lemonade", "biscuit", "crescent roll"],
    "Dish & Cleaning": ["dish soap", "dishwasher soap", "dishwasher detergent", "sponge", "scrubber",
                        "dish scrubber", "drano", "windex", "swiffer", "cleaner", "bleach"],
    "Health & Personal Care": ["toothpaste", "toothbrush", "floss", "shampoo", "conditioner", "body wash",
                               "deodorant", "razor", "shaving cream", "lotion", "advil", "tylenol",
                               "ibuprofen", "q tip", "tampon", "contact solution", "eyedrop", "hand soap"],
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


def staple_keys(staple: Staple) -> set[str]:
    """Keys an ingredient line naming this staple can have: its own, and the one parse_line gives its name,
    which drops anything in parentheses ("Hamburger meat (family pack)" → "hamburger meat")."""
    return {k for k in (staple.name_key, parse_line(staple.name).name_key) if k}


def staple_index(session: Session) -> dict[str, Section]:
    """Every staple key mapped to its section, built once for guessing many lines. The oldest staple wins a
    shared key, as in staple_section."""
    index: dict[str, Section] = {}
    stmt = select(Staple).where(Staple.section_id.is_not(None)).options(selectinload(Staple.section)).order_by(Staple.id)
    for staple in session.scalars(stmt):
        for key in staple_keys(staple):
            index.setdefault(key, staple.section)
    return index


def staple_section(session: Session, key: str, staples: dict[str, Section] | None = None) -> Section | None:
    if staples is not None:
        return staples.get(key)
    for staple in session.scalars(select(Staple).where(Staple.section_id.is_not(None)).order_by(Staple.id)):
        if key in staple_keys(staple):
            return staple.section
    return None


def guess_section(session: Session, key: str, staples: dict[str, Section] | None = None) -> Section:
    """`staples` is a staple_index(), for callers guessing many lines in a row."""
    learned = session.get(ItemSectionMap, key)
    if learned is not None:
        return learned.section
    from_staple = staple_section(session, key, staples)
    if from_staple is not None:
        return from_staple
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


def sign_bg(hex_color: str) -> str:
    """A section's color as a dark tinted heading bar, darkened further if white text wouldn't pass WCAG AA on it."""
    channels = [int(hex_color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    for share in (0.62, 0.5, 0.4, 0.3):
        mixed = "#" + "".join(f"{round(c * share + d * (1 - share)):02x}" for c, d in zip(channels, (10, 13, 15)))
        if 1.05 / (_luminance(mixed) + 0.05) >= 4.5:
            break
    return mixed
