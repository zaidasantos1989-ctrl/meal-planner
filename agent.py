from datetime import date, timedelta
import json
import os
import random
import re

from db import AISLES, DEFAULT_CATEGORIES
from google.cloud import storage
from google.oauth2 import service_account
from pydantic import BaseModel
import streamlit as st

import importlib


def _load_local_fallback_recipes() -> list[dict]:
    """Safely loads recipes without triggering any linter/IDE warnings."""
    # 1. Try recipes.json first
    if os.path.exists("recipes.json"):
        try:
            with open("recipes.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 2. Try recipes.py dynamically (no warnings in VS Code)
    try:
        recipes_mod = importlib.import_module("recipes")
        return getattr(recipes_mod, "RECIPE_DATABASE", [])
    except Exception:
        return []

@st.cache_data(ttl=3600)
def load_recipes_from_gcs() -> list[dict]:
    """Loads recipes from GCS bucket, with safe fallback to local files."""
    fallback = _load_local_fallback_recipes()

    try:
        bucket_name = st.secrets.get("GCS_BUCKET_NAME", "meal-planner-recipe")
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


# ----------------- GCS Recipe Loader with Safe Fallback -----------------
@st.cache_data(ttl=3600)
def load_recipes_from_gcs() -> list[dict]:
    """Loads all recipes from GCS bucket, with automatic fallback to local catalog."""
    try:
        bucket_name = st.secrets.get("GCS_BUCKET_NAME", "meal-planner-recipe")
        info = st.secrets.get("gcp_service_account")
        if not info:
            return RECIPE_DATABASE

        credentials = service_account.Credentials.from_service_account_info(info)
        client = storage.Client(credentials=credentials)
        bucket = client.bucket(bucket_name)

        recipes = []
        blobs = bucket.list_blobs(prefix="recipes/")

        for blob in blobs:
            if blob.name.endswith(".json"):
                try:
                    data = json.loads(blob.download_as_text(encoding="utf-8"))
                    recipes.append(data)
                except Exception as e:
                    print(f"Error loading {blob.name}: {e}")

        return recipes if recipes else RECIPE_DATABASE
    except Exception as e:
        print(f"GCS load failed: {e}. Falling back to local database.")
        return RECIPE_DATABASE


def _categories(profile) -> list[str]:
    return [
        c for c in (profile.categories or DEFAULT_CATEGORIES).split(",") if c
    ]


def _filter_recipes(recipes: list[dict], profile, category: str = None) -> list[dict]:
    """Filters recipes by allergies, dislikes, and category."""
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
        if category and r.get("category", "").lower() != category.lower():
            continue

        ing_names = [i["name"].lower() for i in r.get("ingredients", [])]
        has_allergy = any(
            any(a in name for a in allergies) for name in ing_names
        )
        has_dislike = any(any(d in name for d in dislikes) for name in ing_names)

        if not has_allergy and not has_dislike:
            available.append(r)

    # Fallback to category pool if filters eliminate everything
    if not available:
        available = [
            r
            for r in recipes
            if (not category or r.get("category", "").lower() == category.lower())
        ]

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

    # 2. Check if user mentioned guests or festive dinner in note
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

    filtered_pool = _filter_recipes(all_recipes, profile)
    weekday_pool = [r for r in filtered_pool if not r.get("festive")]
    festive_pool = [r for r in filtered_pool if r.get("festive")]

    if not weekday_pool:
        weekday_pool = filtered_pool
    if not festive_pool:
        festive_pool = filtered_pool

    random.shuffle(weekday_pool)
    random.shuffle(festive_pool)

    selected_meals = []
    w_idx = 0
    f_idx = 0

    # 3. Assemble the meal plan with unshortened steps and exact URLs
    for day in range(1, days + 1):
        current_date = start + timedelta(days=day - 1)
        is_saturday = current_date.weekday() == 5

        for m_type in meal_types:
            # Saturday dinner or guest request gets an elevated recipe
            if m_type == "dinner" and (
                wants_festive
                and (is_saturday or day == 6 or "lördag" in note_lower)
            ):
                recipe = festive_pool[f_idx % len(festive_pool)]
                f_idx += 1
                badge = (
                    "✨ **Bjudmiddag / Helglyx** ✨\n\n"
                    if language == "Svenska"
                    else "✨ **Guest / Dinner Party Special** ✨\n\n"
                )
            else:
                cat = categories[(day - 1) % len(categories)]
                cat_pool = [
                    r
                    for r in weekday_pool
                    if r.get("category", "").lower() == cat.lower()
                ]
                recipe = (
                    cat_pool[w_idx % len(cat_pool)]
                    if cat_pool
                    else weekday_pool[w_idx % len(weekday_pool)]
                )
                w_idx += 1
                badge = ""

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

            # Append the real, working URL directly to instructions
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
                    category=recipe.get("category", "meat"),
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