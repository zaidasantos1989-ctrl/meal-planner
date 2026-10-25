import os

# 1. Clear corporate proxy for this script only (work laptop safe)
for k in [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
]:
    os.environ.pop(k, None)

import json
import re
from google import genai
from google.genai import types
from pydantic import BaseModel
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 2. Tell requests session to ignore system proxy settings
session = requests.Session()
session.trust_env = False

# 3. Add any URLs you want to add to your database here!
URLS_TO_IMPORT = [
    # ICA
    "https://www.ica.se/recept/flygande-jacob-1456/",
    "https://www.ica.se/recept/korvstroganoff-med-ris-712808/",
    "https://www.ica.se/recept/halloumigryta-722841/",
    # Köket.se
    "https://www.koket.se/klassiska-kottbullar-med-graddsas",
    "https://www.koket.se/kramig-laxpasta-med-citron-och-dill",
    "https://www.koket.se/helstekt-flaskfile-med-potatisgratang-och-rodvinssas",
    # Arla.se
    "https://www.arla.se/recept/torsk-med-eggsas/",
    "https://www.arla.se/recept/kyckling-i-dragonsas/",
    "https://www.arla.se/recept/roding-med-vitvinssas/",
    # Zeinas Kitchen
    "https://zeinaskitchen.se/kycklingpasta-med-soltorkade-tomater/",
]

AISLES = [
    "Produce",
    "Meat & Seafood",
    "Meat",
    "Poultry",
    "Dairy",
    "Bakery",
    "Pantry",
    "Spices & Seasonings",
    "Frozen",
    "Canned Goods",
    "Grains & Pasta",
    "Other",
]


class Ingredient(BaseModel):
    name: str
    quantity: float  # Normalized for 1 person
    unit: str
    aisle: str


class Recipe(BaseModel):
    title: str
    category: str
    festive: bool
    source_name: str
    url: str
    prep_minutes: int
    instructions: str
    ingredients: list[Ingredient]


def get_api_key():
    secrets_path = ".streamlit/secrets.toml"
    if os.path.exists(secrets_path):
        with open(secrets_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("GEMINI_API_KEY"):
                    return line.split("=")[1].strip().strip('"').strip("'")
    return os.environ.get("GEMINI_API_KEY")


def clean_html_to_text(html: str) -> str:
    """Strips HTML tags using built-in Python tools (no BeautifulSoup needed)."""
    # Remove script, style, nav, and footer blocks
    text = re.sub(
        r"<(script|style|nav|footer|header)[^>]*>.*?</\1>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Remove all HTML tags (<p>, <div>, <span>, etc.)
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse multiple spaces and linebreaks
    text = re.sub(r"\s+", " ", text).strip()
    return text[:12000]


def scrape_recipe(client, url):
    print(f"📥 Fetching: {url}...")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    resp = session.get(url, headers=headers, timeout=15, verify=False)
    resp.raise_for_status()

    # Clean text without needing bs4
    page_text = clean_html_to_text(resp.text)

    prompt = f"""
    You are an expert recipe parser. Extract the authentic recipe details from this webpage text.
    
    URL: {url}
    Webpage Content:
    {page_text}

    RULES:
    1. title: Exact verbatim title from the webpage.
    2. category: Must be one of: pasta, chicken, meat, fish, vegetarian, vegan, soup, salad, rice & noodles.
    3. festive: Set to True if it is an elevated weekend/guest dish (e.g. oxfilé, rödvinsgryta, lamm, gratäng). Set to False if standard vardagsmat.
    4. prep_minutes: Approximate minutes.
    5. instructions: Copy the step-by-step instructions VERBATIM as numbered steps (1., 2., 3., etc.). Do not summarize.
    6. ingredients: Break down all ingredients.
    7. aisle: Must be one of: {", ".join(AISLES)}.
    8. source_name: Name of website (e.g. 'ICA.se', 'Köket.se', 'Arla.se', 'Zeinas Kitchen').
    """

    res = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=Recipe
        ),
    )
    return json.loads(res.text)


def main():
    api_key = get_api_key()
    if not api_key:
        print("❌ Could not find GEMINI_API_KEY in .streamlit/secrets.toml")
        return

    client = genai.Client(api_key=api_key)

    database_file = "recipes.json"
    recipes = []
    if os.path.exists(database_file):
        with open(database_file, "r", encoding="utf-8") as f:
            recipes = json.load(f)

    existing_urls = {r.get("url") for r in recipes}

    for url in URLS_TO_IMPORT:
        if url in existing_urls:
            print(f"⏩ Already in database: {url}")
            continue

        try:
            recipe = scrape_recipe(client, url)
            recipe["url"] = url  # Keep the exact URL
            recipes.append(recipe)
            existing_urls.add(url)
            print(f"✅ Successfully added: {recipe['title']}")
        except Exception as e:
            print(f"❌ Failed to parse {url}: {e}")

    with open(database_file, "w", encoding="utf-8") as f:
        json.dump(recipes, f, ensure_ascii=False, indent=2)

    print(
        f"\n🎉 Done! Total recipes in {database_file}: {len(recipes)} recipes."
    )


if __name__ == "__main__":
    main()