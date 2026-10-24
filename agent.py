from datetime import date
import re

from db import AISLES, DEFAULT_CATEGORIES
from google import genai
from google.genai import types
from pydantic import BaseModel

MAX_ATTEMPTS = 3
ALL_CATEGORIES = [
    "pasta",
    "chicken",
    "meat",
    "fish",
    "vegetarian",
    "vegan",
    "soup",
    "salad",
    "rice & noodles",
]

# Bilingual Allergen Terms (English + Swedish)
_DAIRY = [
    "milk",
    "cheese",
    "butter",
    "cream",
    "yogurt",
    "yoghurt",
    "parmesan",
    "mozzarella",
    "feta",
    "ricotta",
    "mascarpone",
    "ghee",
    "creme fraiche",
    "mjölk",
    "ost",
    "smör",
    "grädde",
    "vispgrädde",
    "matlagningsgrädde",
    "fil",
    "kvarg",
    "keso",
]
_FISH = [
    "fish",
    "salmon",
    "tuna",
    "cod",
    "haddock",
    "trout",
    "sardine",
    "anchovy",
    "mackerel",
    "tilapia",
    "sea bass",
    "hake",
    "pollock",
    "fisk",
    "lax",
    "tonfisk",
    "torsk",
    "kolja",
    "öring",
    "sill",
    "strömming",
    "makrill",
    "sej",
    "abborre",
    "gös",
]
_SHELLFISH = [
    "shrimp",
    "prawn",
    "crab",
    "lobster",
    "mussel",
    "clam",
    "oyster",
    "scallop",
    "squid",
    "calamari",
    "räka",
    "räkor",
    "kräfta",
    "kräftor",
    "krabba",
    "hummer",
    "mussla",
    "musslor",
    "ostron",
    "bläckfisk",
    "scampi",
]

ALLERGEN_TERMS = {
    "nut": [
        "nut",
        "almond",
        "walnut",
        "cashew",
        "pecan",
        "hazelnut",
        "pistachio",
        "macadamia",
        "peanut",
        "praline",
        "marzipan",
        "pesto",
        "nutella",
        "nöt",
        "nötter",
        "mandel",
        "mandlar",
        "valnöt",
        "valnötter",
        "pekannöt",
        "hasselnöt",
        "pistage",
        "jordnöt",
        "marsipan",
    ],
    "peanut": ["peanut", "satay", "jordnöt", "jordnötter", "jordnötssmör"],
    "gluten": [
        "wheat",
        "flour",
        "pasta",
        "spaghetti",
        "penne",
        "fusilli",
        "tagliatelle",
        "lasagne",
        "lasagna",
        "orzo",
        "gnocchi",
        "noodle",
        "bread",
        "breadcrumb",
        "panko",
        "couscous",
        "barley",
        "rye",
        "bulgur",
        "semolina",
        "tortilla",
        "pita",
        "soy sauce",
        "vete",
        "vetemjöl",
        "mjöl",
        "spagetti",
        "bröd",
        "ströbröd",
        "korn",
        "råg",
        "mannagryn",
        "sojasås",
    ],
    "dairy": _DAIRY,
    "lactose": _DAIRY,
    "milk": _DAIRY,
    "egg": ["egg", "mayonnaise", "mayo", "aioli", "ägg", "majonnäs", "majo"],
    "fish": _FISH,
    "shellfish": _SHELLFISH,
    "crustacean": _SHELLFISH,
    "seafood": _FISH + _SHELLFISH,
    "soy": ["soy", "tofu", "edamame", "tempeh", "miso", "soja", "sojasås"],
    "sesame": ["sesame", "tahini", "sesam", "sesamfrö"],
    "celery": ["celery", "celeriac", "selleri", "stjälkselleri", "rotselleri"],
    "mustard": ["mustard", "senap"],
}

_PLANT_MILK = re.compile(
    r"\b(coconut|oat|soy|almond|rice|plant|kokos|havre|soja|mandel|ris|växtbaserad)\s+(milk|cream|yogurt|yoghurt|mjölk|grädde|dryck)"
)


class IngredientOut(BaseModel):
    name: str
    quantity: float
    unit: str
    aisle: str


class MealOut(BaseModel):
    day: int
    meal_type: str
    title: str
    category: str
    prep_minutes: int
    instructions: str
    ingredients: list[IngredientOut]


class PlanOut(BaseModel):
    meals: list[MealOut]


def _categories(profile) -> list[str]:
    return [
        c for c in (profile.categories or DEFAULT_CATEGORIES).split(",") if c
    ]


def _banned_terms(allergies: str) -> set[str]:
    terms = set()
    for raw in allergies.split(","):
        a = raw.strip().lower()
        if not a:
            continue
        terms.add(a[:-1] if a.endswith("s") else a)
        for key, words in ALLERGEN_TERMS.items():
            if key in a:
                terms.update(words)
    return terms


def _allergy_problems(meals: list[MealOut], banned: set[str]) -> list[str]:
    problems = []
    for m in meals:
        for ing in m.ingredients:
            name = ing.name.lower()
            if re.search(r"free\b|fri\b|vegan|plant-based|växtbaserad", name):
                continue
            name = _PLANT_MILK.sub(r"\1", name)
            for t in banned:
                if re.search(rf"\b{re.escape(t)}(s|es|ar|er|or)?\b", name):
                    problems.append(
                        f'Day {m.day} "{m.title}" uses "{ing.name}", which conflicts '
                        f"with the allergy list ({t}). Replace it."
                    )
                    break
    return problems


def _household_rules(profile, is_swedish: bool) -> str:
    if is_swedish:
        return f"""Hushåll: {profile.people} personer.
STRIKTA allergier - använd ALDRIG dessa eller ingredienser som innehåller dem: {profile.allergies or "inga"}.
Ogillar - undvik: {profile.dislikes or "inga"}.
Önskemål: {profile.preferences or "inga"}.
Max tillagningstid: {profile.max_minutes} minuter.

Regler för receptval och formatering (KRITISKT):
- RIKTIGA RECEPT: Du MÅSTE välja faktiska, beprövade recept från etablerade svenska matsajter (Köket.se, ICA.se, Arla.se, Coop.se, Tasteline eller Zeinas Kitchen). Hitta ALDRIG på egna recept!
- KÄLLANVISNING: I slutet av instruktionerna, ange alltid källan som text (t.ex. 'Källa: Köket.se' eller 'Källa: ICA.se'). Skriv ALDRIG ut påhittade URL-adresser.
- SPRÅK: Skriv ALLA receptnamn, instruktioner och ingredienser helt på svenska.
- KOLHYDRAT/TILLBEHÖR: Varje måltid MÅSTE paras ihop med ett passande kolhydrattillbehör som MÅSTE inkluderas i ingredienslistan för {profile.people} personer så att det hamnar på inköpslistan.
- Mängder är anpassade för {profile.people} personer i metriska enheter: g, kg, dl, l, st, msk, tsk.
- Använd korta, tydliga ingrediensnamn på svenska ("gul lök", "kycklingfilé", "krossade tomater", "basmatiris").
- aisle MÅSTE vara en av följande: {", ".join(AISLES)}.
- instructions: MÅSTE vara en tydligt numrerad lista där varje steg börjar på en ny rad med '1. ', '2. ', '3. '."""
    else:
        return f"""Household: {profile.people} people.
STRICT allergies - never use these or any ingredient containing them: {profile.allergies or "none"}.
Dislikes - avoid: {profile.dislikes or "none"}.
Preferences: {profile.preferences or "none"}.
Max cooking time: {profile.max_minutes} minutes.

Recipe Selection & Formatting Rules (CRITICAL):
- REAL RECIPES: You MUST choose real, published recipes from established Swedish recipe websites (Köket.se, ICA.se, Arla.se, Coop.se, Tasteline, or Zeinas Kitchen). Never invent fictional dishes!
- SOURCE ATTRIBUTION: At the end of the instructions, always mention the source name (e.g. 'Source: Köket.se' or 'Source: ICA.se'). Never write out fake URL links.
- LANGUAGE: Write all titles, ingredients, and instructions in English.
- CARBOHYDRATE SIDE: Every meal MUST pair with an ideal carbohydrate side dish included in the ingredients list for {profile.people} people.
- Ingredient quantities are for {profile.people} people, in metric units: g, kg, ml, l, pcs, tbsp, tsp.
- aisle must be one of: {", ".join(AISLES)}.
- instructions: MUST be formatted as a numbered list with each step starting on a new line with '1. ', '2. ', '3. '."""


def _run(api_key, model, prompt, schema, check, on_step=None):
    """Generate -> validate -> ask for a fix, until the checks pass or attempts run out."""
    client = genai.Client(api_key=api_key)
    problems, result = [], None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        text = prompt
        if problems:
            text += (
                "\n\nYour previous answer was rejected. Fix ALL of these problems:\n- "
                + "\n- ".join(problems)
            )
        resp = client.models.generate_content(
            model=model,
            contents=text,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.7,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        result = (
            resp.parsed
            if resp.parsed is not None
            else schema.model_validate_json(resp.text)
        )
        problems = check(result)
        if on_step:
            on_step(attempt, problems)
        if not problems:
            break
    return result, problems


def plan_meals(
    profile,
    start: date,
    days: int,
    meal_types: list[str],
    note: str,
    api_key: str,
    model: str,
    on_step=None,
    language: str = "English",
):
    is_swedish = (
        language.lower() == "svenska"
        or "svenska" in note.lower()
        or "swedish" in note.lower()
    )
    categories = _categories(profile)
    banned = _banned_terms(profile.allergies or "")

    prompt = f"""You are a friendly home-cooking meal planner.
Create a {days}-day plan starting {start:%A %d %B %Y}.
For every day create exactly one meal for each of: {", ".join(meal_types)}.
Rotate between these categories, spread evenly: {", ".join(categories)}.
Never use the same category on two consecutive days for the same meal type, and never repeat a dish.
{"Lunches should be lighter and quick." if "lunch" in meal_types else ""}
Special request this time: {note or "none"}.

{_household_rules(profile, is_swedish)}
- day is a number from 1 to {days}; meal_type is one of {meal_types}; category is one of {categories}."""

    def check(plan: PlanOut) -> list[str]:
        problems = []
        expected = {(d, t) for d in range(1, days + 1) for t in meal_types}
        got = [(m.day, m.meal_type.lower()) for m in plan.meals]
        if missing := expected - set(got):
            problems.append(
                "Missing meals for: "
                + ", ".join(f"day {d} {t}" for d, t in sorted(missing))
            )
        if extra := set(got) - expected:
            problems.append(
                "Unexpected meals for: "
                + ", ".join(f"day {d} {t}" for d, t in sorted(extra))
            )
        if len(got) != len(set(got)):
            problems.append(
                "Some day/meal slots have more than one meal; give exactly one per slot."
            )
        if bad := {
            m.category
            for m in plan.meals
            if m.category.lower() not in categories
        }:
            problems.append(
                f"Invalid categories {sorted(bad)}; use only {categories}."
            )
        used = {m.category.lower() for m in plan.meals}
        if len(expected) >= len(categories) and (
            unused := [c for c in categories if c not in used]
        ):
            problems.append(
                f"These categories are never used: {', '.join(unused)}."
            )

        titles = [m.title.lower() for m in plan.meals]
        if dups := {t for t in titles if titles.count(t) > 1}:
            problems.append(f"Repeated dishes: {', '.join(dups)}.")
        return problems + _allergy_problems(plan.meals, banned)

    return _run(api_key, model, prompt, PlanOut, check, on_step)


def swap_meal(
    profile,
    day: int,
    meal_type: str,
    category: str,
    existing_titles: list[str],
    api_key: str,
    model: str,
    language: str = "English",
):
    is_swedish = (
        language.lower() == "svenska"
        or "svenska" in (profile.preferences or "").lower()
    )
    banned = _banned_terms(profile.allergies or "")
    taken = {t.lower() for t in existing_titles}

    prompt = f"""You are a friendly home-cooking meal planner.
Suggest ONE {meal_type} in the category "{category}".
It must be different from these dishes already in the plan: {", ".join(existing_titles)}.

{_household_rules(profile, is_swedish)}
- day = {day}; meal_type = "{meal_type}"; category = "{category}"."""

    def check(m: MealOut) -> list[str]:
        problems = _allergy_problems([m], banned)
        if m.title.lower() in taken:
            problems.append(
                f'"{m.title}" is already in the plan; suggest something else.'
            )
        return problems

    meal, problems = _run(api_key, model, prompt, MealOut, check)
    meal.category = category
    return meal, problems