from datetime import date, timedelta
import importlib
import json
import os
import random
import re

from db import AISLES, DEFAULT_CATEGORIES
from google.cloud import storage
from google.oauth2 import service_account
from pydantic import BaseModel
import streamlit as st

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

# Bilingual Allergen Terms
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


# ----------------- Fallback & GCS Loader -----------------
def _load_local_fallback_recipes() -> list[dict]:
    """Safely loads recipes without triggering linter warnings."""
    if os.path.exists("recipes.json"):
        try:
            with open("recipes.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    try:
        recipes_mod = importlib.import_module("recipes")
        return getattr(recipes_mod, "RECIPE_DATABASE", [])
    except Exception:
        return []


@st.cache_data(ttl=3600)
def load_recipes_from_gcs() -> list[dict]:
    """Loads all categorized JSON recipes from GCS bucket with safe local fallback."""
    fallback = _load_local_fallback_recipes()
    try:
        bucket_name = st.secrets.get(
            "GCS_BUCKET_NAME", "meal-planner-recipes-zaida"
        )
        info = st.secrets.get("gcp_service_account")
        if not info:
            return fallback

        credentials = service_account.Credentials.from_service_account_info(
            info
        )
        client = storage.Client(credentials=credentials)
        bucket = client.bucket(bucket_name)

        recipes_list = []
        blobs = bucket.list_blobs(prefix="recipes/")

        for blob in blobs:
            if blob.name.endswith(".json"):
                try:
                    data = json.loads(blob.download_as_text(encoding="utf-8"))
                    recipes_list.append(data)
                except Exception as e:
                    print(f"Error loading {blob.name}: {e}")

        return recipes_list if recipes_list else fallback
    except Exception as e:
        print(f"GCS load failed: {e}. Using local fallback.")
        return fallback


def _categories(profile) -> list[str]:
    return [
        c for c in (profile.categories or DEFAULT_CATEGORIES).split(",") if c
    ]


def _matches_category(recipe: dict, category: str) -> bool:
    """Matches user category rotation to recipe category and protein tags."""
    cat = category.lower()
    r_cat = recipe.get("category", "").lower()
    r_protein = recipe.get("protein", "").lower()

    if r_cat == cat or r_protein == cat:
        return True

    # Broader protein mappings
    if cat == "meat" and r_protein in ["beef", "pork", "meat"]:
        return True
    if cat == "chicken" and r_protein in ["chicken", "poultry"]:
        return True
    if cat == "fish" and r_protein in ["fish", "seafood"]:
        return True
    if cat == "vegetarian" and r_protein in ["vegetarian", "vegan"]:
        return True

    return False


def _filter_recipes(
    recipes: list[dict], profile, category: str = None
) -> list[dict]:
    """Filters recipes by allergies and dislikes."""
    allergies = [
        a.strip().lower()
        for a in (profile.allergies or "").split(",")
        if a.strip()
    ]
    dislikes = [
        d.strip().lower()
        for d in (profile.dislikes or "").split(",")
        if d.strip()
    ]

    available = []
    for r in recipes:
        if category and not _matches_category(r, category):
            continue

        ing_names = [i["name"].lower() for i in r.get("ingredients", [])]
        has_allergy = any(
            any(a in name for a in allergies) for name in ing_names
        )
        has_dislike = any(any(d in name for d in dislikes) for name in ing_names)

        if not has_allergy and not has_dislike:
            available.append(r)

    if not available and category:
        # Fallback to category ignoring strict dislikes
        available = [r for r in recipes if _matches_category(r, category)]

    return available if available else recipes


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
    people = max(1, getattr(profile, "people", 2))
    categories = _categories(profile)

    # 1. Load real recipes from GCS (or local fallback)
    all_recipes = load_recipes_from_gcs()
    if not all_recipes:
        return PlanOut(meals=[]), ["No recipes found in GCS or local database."]

    # 2. Check if user requested guest or festive dinner
    note_lower = (note or "").lower()
    guest_keywords = [
        "gäst",
        "guest",
        "bjudning",
        "fest",
        "helg",
        "lördag",
        "saturday",
        "fint",
    ]
    wants_festive = any(k in note_lower for k in guest_keywords)

    safe_pool = _filter_recipes(all_recipes, profile)

    # Separate into occasions
    everyday_pool = [
        r
        for r in safe_pool
        if r.get("occasion") == "everyday" and not r.get("festive")
    ]
    weekend_pool = [
        r
        for r in safe_pool
        if r.get("occasion") == "weekend" and not r.get("festive")
    ]
    guest_pool = [
        r
        for r in safe_pool
        if r.get("occasion") == "guest" or r.get("festive")
    ]

    # Fallback pools if a category is missing
    if not everyday_pool:
        everyday_pool = safe_pool
    if not weekend_pool:
        weekend_pool = everyday_pool
    if not guest_pool:
        guest_pool = weekend_pool

    selected_meals = []
    used_titles = set()

    for day in range(1, days + 1):
        current_date = start + timedelta(days=day - 1)
        weekday_num = current_date.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun

        for m_type in meal_types:
            cat = categories[(day - 1) % len(categories)]

            # 3. Choose occasion based on day of the week
            if m_type == "dinner" and (
                (wants_festive and (weekday_num == 5 or "lördag" in note_lower))
                or weekday_num == 5
            ):
                # Saturday or Guest day -> Bjudmiddag
                target_pool = guest_pool
                badge = (
                    "✨ **Bjudmiddag / Helglyx** ✨\n\n"
                    if language == "Svenska"
                    else "✨ **Guest / Dinner Party Special** ✨\n\n"
                )
            elif m_type == "dinner" and weekday_num in [4, 6]:
                # Friday or Sunday -> Mysig helgmat
                target_pool = weekend_pool
                badge = ""
            else:
                # Monday to Thursday or lunch -> Snabb vardagsmat
                target_pool = everyday_pool
                badge = ""

            # Filter target pool by requested category
            cat_candidates = [
                r
                for r in target_pool
                if _matches_category(r, cat) and r["title"] not in used_titles
            ]
            if not cat_candidates:
                cat_candidates = [
                    r for r in target_pool if _matches_category(r, cat)
                ]
            if not cat_candidates:
                cat_candidates = [
                    r for r in safe_pool if r["title"] not in used_titles
                ]
            if not cat_candidates:
                cat_candidates = safe_pool

            recipe = random.choice(cat_candidates)
            used_titles.add(recipe["title"])

            # Scale quantities for household size
            scaled_ingredients = [
                IngredientOut(
                    name=i["name"],
                    quantity=round(i["quantity"] * people, 1),
                    unit=i["unit"],
                    aisle=i["aisle"],
                )
                for i in recipe.get("ingredients", [])
            ]

            # Append the real source link to the verbatim steps
            source_url = recipe.get("url", "")
            source_name = recipe.get("source_name", "Källsidan")
            link_markdown = (
                f"\n\n🔗 **Receptkälla:** [{recipe['title']} på {source_name}]({source_url})"
                if source_url
                else ""
            )

            full_instructions = (
                f"{badge}{recipe.get('instructions', '')}{link_markdown}"
            )

            selected_meals.append(
                MealOut(
                    day=day,
                    meal_type=m_type,
                    title=recipe["title"],
                    category=recipe.get("category", cat),
                    prep_minutes=recipe.get("prep_minutes", 30),
                    instructions=full_instructions,
                    ingredients=scaled_ingredients,
                )
            )

    if on_step:
        on_step(1, [])

    return PlanOut(meals=selected_meals), []


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
    """Swaps for another real recipe from GCS in the selected category."""
    people = max(1, getattr(profile, "people", 2))
    all_recipes = load_recipes_from_gcs()

    pool = _filter_recipes(all_recipes, profile, category)
    filtered = [
        r for r in pool if r.get("title", "") not in set(existing_titles)
    ]
    recipe = random.choice(filtered if filtered else pool)

    scaled_ingredients = [
        IngredientOut(
            name=i["name"],
            quantity=round(i["quantity"] * people, 1),
            unit=i["unit"],
            aisle=i["aisle"],
        )
        for i in recipe.get("ingredients", [])
    ]

    source_url = recipe.get("url", "")
    source_name = recipe.get("source_name", "Källsidan")
    link_markdown = (
        f"\n\n🔗 **Receptkälla:** [{recipe['title']} på {source_name}]({source_url})"
        if source_url
        else ""
    )

    full_instructions = f"{recipe.get('instructions', '')}{link_markdown}"

    return (
        MealOut(
            day=day,
            meal_type=meal_type,
            title=recipe["title"],
            category=recipe.get("category", category),
            prep_minutes=recipe.get("prep_minutes", 30),
            instructions=full_instructions,
            ingredients=scaled_ingredients,
        ),
        [],
    )