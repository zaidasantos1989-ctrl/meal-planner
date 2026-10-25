import os

# Clear proxy for SEB laptop
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
import time
from urllib.parse import urljoin, urlparse
from google import genai
from google.cloud import storage
from google.genai import types
from google.oauth2 import service_account
from pydantic import BaseModel, Field
import requests
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
session = requests.Session()
session.trust_env = False

# ----------------- Automated Discovery Hubs -----------------
# The script will visit these hubs and auto-discover recipes
DISCOVERY_HUBS = [
    "https://zeinaskitchen.se/category/middag/",
    "https://zeinaskitchen.se/category/kyckling/",
    "https://zeinaskitchen.se/category/fisk-och-skaldjur/",
    "https://zeinaskitchen.se/category/kottfars/",
    "https://www.arla.se/recept/vardag/",
    "https://www.arla.se/recept/helg/",
]

MAX_RECIPES_PER_RUN = (
    15  # Harvest 15 recipes at a time to stay within quotas
)

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


class HarvestedRecipe(BaseModel):
    title: str = Field(description="Exact verbatim recipe title from the page")
    protein: str = Field(
        description="One of: chicken, beef, pork, fish, seafood, vegetarian, vegan"
    )
    occasion: str = Field(
        description="One of: 'everyday' (quick weekday food), 'weekend' (comfort food), 'guest' (festive dinner party)"
    )
    category: str = Field(
        description="One of: pasta, chicken, meat, fish, vegetarian, vegan, soup, salad, rice & noodles"
    )
    source_name: str
    prep_minutes: int
    instructions: str = Field(
        description="Full, verbatim numbered steps (1., 2., 3.)"
    )
    ingredients: list[Ingredient]


def get_gcs_bucket():
    bucket_name = st.secrets.get(
        "GCS_BUCKET_NAME", "meal-planner-recipes-zaida"
    )
    info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(info)
    client = storage.Client(credentials=credentials)
    return client.bucket(bucket_name)


def clean_html(html: str) -> str:
    text = re.sub(
        r"<(script|style|nav|footer|header)[^>]*>.*?</\1>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:14000]


def auto_discover_links(hub_url: str, existing_urls: set) -> list[str]:
    """Scans hub page and automatically discovers recipe links."""
    print(f"🔎 Scanning hub: {hub_url}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "sv-SE,sv;q=0.9",
    }
    try:
        resp = session.get(hub_url, headers=headers, timeout=15, verify=False)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ❌ Could not open hub: {e}")
        return []

    found = re.findall(r'href=[\'"]?([^\'" >]+)', resp.text)
    base_domain = urlparse(hub_url).netloc
    recipe_links = []

    for link in found:
        full_url = urljoin(hub_url, link).split("?")[0].rstrip("/")
        if base_domain in full_url:
            # Exclude non-recipe system pages
            if not any(
                skip in full_url
                for skip in [
                    "/category/",
                    "/tag/",
                    "/page/",
                    "/om-",
                    "/kontakt",
                    "#",
                    "/artiklar/",
                ]
            ):
                if (
                    full_url not in existing_urls
                    and full_url not in recipe_links
                ):
                    recipe_links.append(full_url)

    print(f"  ✨ Found {len(recipe_links)} candidate recipe links.")
    return recipe_links


def parse_and_classify_recipe(client, url: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "sv-SE,sv;q=0.9",
    }
    resp = session.get(url, headers=headers, timeout=15, verify=False)
    resp.raise_for_status()
    page_text = clean_html(resp.text)

    prompt = f"""
    Extract the recipe from this webpage.
    URL: {url}
    Content:
    {page_text}

    RULES:
    1. title: Exact verbatim recipe title.
    2. protein: One of: chicken, beef, pork, fish, seafood, vegetarian, vegan.
    3. occasion: Classify accurately:
       - 'everyday' for quick 20-30 min vardagsmat (korv stroganoff, enkel pasta).
       - 'weekend' for cozy weekend food (lasagne, grytor, tacos).
       - 'guest' for elevated dinner party / festmåltid (oxfilé, röding, rödvinssås, gratäng).
    4. category: One of: pasta, chicken, meat, fish, vegetarian, vegan, soup, salad, rice & noodles.
    5. instructions: Copy the cooking steps VERBATIM as numbered steps (1., 2., 3., etc.). Do not shorten.
    6. ingredients: Break down all ingredients. Normalize quantity for exactly 1 person.
    7. aisle: Must be one of: {", ".join(AISLES)}.
    8. source_name: Source website name (e.g. Arla.se, Zeinas Kitchen, Köket.se, ICA.se).
    """

    res = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=HarvestedRecipe,
        ),
    )
    data = json.loads(res.text)
    data["url"] = url
    return data


def save_to_gcs(bucket, recipe: dict):
    slug = re.sub(r"[^a-zA-Z0-9åäöÅÄÖ]+", "-", recipe["title"].lower()).strip(
        "-"
    )
    protein = recipe.get("protein", "other").lower()

    # Save to: recipes/chicken/flygande-jacob.json
    blob_path = f"recipes/{protein}/{slug}.json"
    blob = bucket.blob(blob_path)

    blob.upload_from_string(
        json.dumps(recipe, ensure_ascii=False, indent=2),
        content_type="application/json",
    )
    print(
        f"  ☁️ Saved to GCS: {blob_path} [{recipe['occasion'].upper()} | {recipe['protein'].upper()}]"
    )


def main():
    api_key = st.secrets.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    bucket = get_gcs_bucket()
    print(f"📦 Connected to GCS Bucket: {bucket.name}")

    # Check which URLs already exist in the bucket
    existing_urls = set()
    for blob in bucket.list_blobs(prefix="recipes/"):
        if blob.name.endswith(".json"):
            try:
                data = json.loads(blob.download_as_text(encoding="utf-8"))
                if "url" in data:
                    existing_urls.add(data["url"])
            except Exception:
                pass

    print(f"📚 Currently {len(existing_urls)} recipes already stored in GCS.")

    # 1. Automatically discover new recipe links from hubs
    all_candidates = []
    for hub in DISCOVERY_HUBS:
        all_candidates.extend(auto_discover_links(hub, existing_urls))

    unique_candidates = list(dict.fromkeys(all_candidates))
    to_process = unique_candidates[:MAX_RECIPES_PER_RUN]
    print(f"\n🚀 Harvesting {len(to_process)} new recipes into GCS...\n")

    added = 0
    for url in to_process:
        try:
            print(f"📥 Parsing: {url}")
            recipe_data = parse_and_classify_recipe(client, url)
            save_to_gcs(bucket, recipe_data)
            added += 1
            time.sleep(1)  # Polite 1-second delay
        except Exception as e:
            print(f"  ❌ Failed {url}: {e}")

    print(f"\n🎉 Completed run! Added {added} new categorized recipes to GCS.")


if __name__ == "__main__":
    main()