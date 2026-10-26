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

from collections import defaultdict
import json
import random
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

# ==============================================================================
# 🎯 ACTIVE HUBS (Verified working URLs)
# ==============================================================================
DISCOVERY_HUBS = [
    # Arla (Great working recipe collections)
    "https://www.arla.se/recept/samling/pasta/",
    "https://www.arla.se/recept/samling/snabb-middag/",
    "https://www.arla.se/recept/samling/helgmiddag/",
    "https://www.arla.se/recept/samling/sondagsmiddag/",
    "https://www.arla.se/recept/samling/vardag/",
    "https://www.arla.se/recept/samling/nytt/",
    "https://www.arla.se/recept/samling/middag/",
    # Köket.se
    "https://www.koket.se/mat/typ-av-ratt/grytor",
    "https://www.koket.se/mat/typ-av-maltid/huvudratter",
    "https://www.koket.se/mat/typ-av-maltid/vardagsmiddag",
    # Recepten.se
    "https://www.recepten.se/kategori/kyckling_kalkon.html",
    "https://www.recepten.se/kategori/fisk.html",
    "https://www.recepten.se/kategori/noetkoett.html",
    "https://www.recepten.se/kategori/flaeskkoett.html",
    "https://www.recepten.se/kategori/kvaellsmat.html",
    # Zeina's active working categories
    "https://zeinaskitchen.se/category/kyckling/",
    "https://zeinaskitchen.se/category/vegetariskt/",
    # ICA
    "https://www.ica.se/recept/middag/",
    "https://www.ica.se/recept/huvudratt/",
    "https://www.ica.se/recept/lordag/",
    "https://www.ica.se/recept/sondag/",
    "https://www.ica.se/recept/fredag/",
    # Tasteline
    "https://www.tasteline.com/veckomenyer/",
    # Coop
    "https://www.coop.se/recept/middag/",
]

# Strict blacklist of non-recipe paths, articles, and assets
BLOCKED_PATTERNS = [
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".webp",
    ".ico",
    ".woff",
    "wp-content",
    "wp-includes",
    "wp-json",
    "feed",
    "comments",
    "om-",
    "about",
    "kontakt",
    "kundservice",
    "press",
    "jobb",
    "hallbarhet",
    "mejeri",
    "bonde",
    "artiklar",
    "artikel",
    "produkter",
    "aktuellt",
    "guide",
    "tips",
    "fakta",
    "skola",
    "hur-",
    "basta-",
    "inspiration",
    "veckomeny",
    "portioner",
    "tabell",
    "kategori",
    "tag",
    "page/",
    "#",
]

# Side dishes and accessories that should NEVER be stored as main dinners
SIDE_DISH_WORDS = [
    "potatismos",
    "stuvade makaroner",
    "stuvad makaron",
    "bearnaisesås",
    "gräddsås",
    "remouladsås",
    "dressing",
    "vitlöksbröd",
    "pommes frites",
    "rödvinssås",
    "tzatziki",
    "guacamole",
]

AISLES = [
    "Badrums artiklar",
    "Bröd",
    "Ost och annat",
    "Kött",
    "Frukt och grönt",
    "Fryst",
    "Mejeri",
    "Skafferi",
    "Chips och godis",
    "Övrigt",
]


# ==============================================================================
# 🎯 STRICT RECIPE URL PATTERNS (Whitelisting real recipe URLs only)
# ==============================================================================
def is_valid_recipe_url(url: str, base_domain: str) -> bool:
    """Strictly validates if a URL matches the exact pattern of a real recipe."""
    url_lower = url.lower()
    path = urlparse(url).path.strip("/")
    segments = [s for s in path.split("/") if s]

    # --- ICA.se: Real recipes ALWAYS end in a number (e.g. /recept/korvstroganoff-712808/) ---
    if "ica.se" in base_domain:
        return bool(re.search(r"/recept/[a-z0-9-]+-\d+/?$", url_lower))

    # --- Recepten.se: Real recipes are under /recept/ and end in .html ---
    if "recepten.se" in base_domain:
        return url_lower.startswith("https://www.recepten.se/recept/") and url_lower.endswith(".html")

    # --- Arla.se: Real recipes are strictly /recept/<recipe-slug>/ ---
    if "arla.se" in base_domain:
        if not url_lower.startswith("https://www.arla.se/recept/"):
            return False
        # Must be /recept/<slug> (exactly 2 segments), avoiding /samling/, /teman/, /artiklar/
        if len(segments) != 2:
            return False
        banned = ["samling", "teman", "artiklar", "tips", "halsa", "inspiration", "veckomeny", "nytt"]
        return not any(b in segments[1] for b in banned)

    # --- Köket.se: Real recipes are single-level root slugs (e.g. koket.se/klassisk-biff-rydberg) ---
    if "koket.se" in base_domain:
        if len(segments) != 1:
            return False
        banned = ["mat", "dryck", "artiklar", "kockar", "program", "vin", "kokbocker", "kurser", "om-oss", "tips"]
        return not any(segments[0].startswith(b) for b in banned)

    # --- Zeina's Kitchen: Single-level recipe post slug ---
    if "zeinaskitchen.se" in base_domain:
        if len(segments) != 1:
            return False
        banned = ["category", "tag", "page", "om-zeina", "kontakt", "feed", "comments", "annonsera"]
        return not any(segments[0].startswith(b) for b in banned)

    # --- Coop.se & Tasteline.com ---
    if "coop.se" in base_domain or "tasteline.com" in base_domain:
        return "/recept/" in url_lower and len(segments) == 2

    return False


def auto_discover_links(hub_url: str, existing_urls: set) -> list[str]:
    """Scans hub page and extracts ONLY 100% verified recipe links."""
    if not hub_url or not hub_url.strip():
        return []

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

    # Find all <a href="..."> links
    found_links = re.findall(r"<a\s+[^>]*?href=[\'\"]([^\'\"]+)[\'\"]", resp.text, flags=re.IGNORECASE)
    base_domain = urlparse(hub_url).netloc
    recipe_links = []

    for link in found_links:
        clean_url = urljoin(hub_url, link).split("?")[0].rstrip("/")

        # Apply strict site-specific whitelist
        if is_valid_recipe_url(clean_url, base_domain):
            if clean_url not in existing_urls and clean_url not in recipe_links:
                recipe_links.append(clean_url)

    print(f"  ✨ Found {len(recipe_links)} verified recipe links.")
    return recipe_links


def is_likely_recipe(html_text: str) -> bool:
    """Pre-check: Detects Schema.org Recipe data or Swedish cooking keywords."""
    lower = html_text.lower()
    
    # 1. Official Google Recipe Schema (100% guaranteed recipe)
    if '"@type": "recipe"' in lower or '"@type":"recipe"' in lower:
        return True

    # 2. Swedish recipe section keywords
    has_ing = "ingrediens" in lower or "ingredienser" in lower
    has_steps = (
        "gör så här" in lower
        or "tillagning" in lower
        or "instruktion" in lower
        or "steg för steg" in lower
    )
    return has_ing and has_steps


class Ingredient(BaseModel):
    original_name: str = Field(description="The exact raw ingredient name as written in the recipe text")
    normalized_name: str = Field(description="Clean, standard, singular base name for grocery shopping (e.g., 'Gul lök', 'Vispgrädde')")
    quantity: float
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
    allergens: list[str] = Field(description="List of major allergens present in this dish. Choose from: gluten, dairy, nuts, peanuts, egg, fish, shellfish, soy, sesame, celery, mustard")
    ingredients: list[Ingredient]


def get_gcs_bucket():
    bucket_name = st.secrets.get(
        "GCS_BUCKET_NAME", "meal-planner-recipe"
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


def parse_and_classify_recipe(client, url: str) -> dict | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "sv-SE,sv;q=0.9",
    }
    resp = session.get(url, headers=headers, timeout=15, verify=False)
    resp.raise_for_status()

    # Pre-check: If this is an article or guide without recipe steps, SKIP IT immediately!
    if not is_likely_recipe(resp.text):
        print(f"  ⏭️ Skipping: Blog/article/guide (no recipe sections found).")
        return None

    page_text = clean_html(resp.text)

   prompt = f"""
    You are an expert recipe parser.
    URL: {url}
    Content:
    {page_text}

    CRITICAL RULES:
    1. title: Exact verbatim recipe title.
    2. protein: One of: chicken, beef, pork, fish, seafood, vegetarian, vegan.
    3. occasion: 'everyday', 'weekend', or 'guest'.
    4. category: One of: pasta, chicken, meat, fish, vegetarian, vegan, soup, salad, rice & noodles.
    5. instructions: Verbatim numbered steps (1., 2., 3.). Do not shorten.
    6. ingredients: Break down all ingredients. 
       - For 'original_name', copy the ingredient name exactly as it appears in the text.
       - For 'normalized_name', provide the clean shopping version (remove preparation words like finhackad/tärnad, use singular form).
       - OMIT salt, pepper, cooking oil, water, and rice entirely.
    7. aisle: Must be ONE of these exact categories: {", ".join(AISLES)}. Choose the most appropriate one for a Swedish supermarket.
    8. allergens: Accurately list any major allergens present (e.g., 'gluten' if it has wheat/pasta/bread, 'dairy' if it has milk/butter/cheese/cream, 'fish', etc.).
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
    title_lower = data.get("title", "").lower()

    # 1. Reject non-recipes and side dishes
    if (
        data.get("title") == "INVALID_NOT_A_RECIPE"
        or any(w in title_lower for w in SIDE_DISH_WORDS)
        or len(data.get("ingredients", [])) < 3
    ):
        print(f"  ⏭️ Skipping: '{data.get('title')}' is a side dish or non-recipe.")
        return None

    # 2. Enforce strict category priority in Python
    if "soppa" in title_lower or "soppa" in url.lower():
        data["category"] = "soup"
    elif any(
        p in title_lower
        for p in [
            "pasta",
            "spagetti",
            "spaghetti",
            "lasagne",
            "penne",
            "tagliatelle",
            "makaroner",
        ]
    ):
        data["category"] = "pasta"

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
        f"  ☁️ Saved to GCS: {blob_path} [{recipe['occasion'].upper()} | {recipe['category'].upper()}]"
    )


TARGET_NEW_RECIPES = 60  # Number of REAL recipes to successfully save per run

def main():
    api_key = st.secrets.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    bucket = get_gcs_bucket()
    print(f"📦 Connected to GCS Bucket: {bucket.name}")

    # Read existing URLs to prevent duplicates
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

    # Discover verified recipe links
    by_domain = defaultdict(list)
    for hub in DISCOVERY_HUBS:
        links = auto_discover_links(hub, existing_urls)
        for link in links:
            domain = urlparse(link).netloc
            if link not in by_domain[domain]:
                by_domain[domain].append(link)

    for domain in by_domain:
        random.shuffle(by_domain[domain])

    # Round-robin interleaved queue
    candidates_queue = []
    domains = list(by_domain.keys())
    random.shuffle(domains)

    while any(by_domain.values()):
        for d in domains:
            if by_domain[d]:
                candidates_queue.append(by_domain[d].pop(0))

    print(f"\n🚀 Total verified candidate recipe links available: {len(candidates_queue)}")
    print(f"🎯 Target to save this run: {TARGET_NEW_RECIPES} real recipes.\n")

    added = 0
    for url in candidates_queue:
        if added >= TARGET_NEW_RECIPES:
            break

        try:
            print(f"📥 [{added + 1}/{TARGET_NEW_RECIPES}] Parsing: {url}")
            recipe_data = parse_and_classify_recipe(client, url)
            if recipe_data is None:
                continue

            save_to_gcs(bucket, recipe_data)
            existing_urls.add(url)
            added += 1
            print(f"  ✅ Saved: {recipe_data['title']} ({recipe_data['category'].upper()})")

            time.sleep(4.2)  # Respects Gemini's 15/min free limit
        except Exception as e:
            print(f"  ❌ Failed {url}: {e}")

    print(f"\n🎉 Completed run! Successfully added {added} genuine dinner recipes to GCS.")


if __name__ == "__main__":
    main()