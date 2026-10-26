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
    original_name: str = Field(description="Exact ingredient name as written in source recipe")
    normalized_name: str = Field(description="Clean shopping name, e.g. 'Gul lök'")
    quantity: float
    unit: str
    aisle: str


class HarvestedRecipe(BaseModel):
    title: str = Field(description="Exact verbatim recipe title from the page")
    protein: str = Field(description="One of: chicken, beef, pork, fish, seafood, vegetarian, vegan")
    occasion: str = Field(description="One of: 'everyday', 'weekend', 'guest'")
    category: str = Field(description="One of: pasta, chicken, meat, fish, vegetarian, vegan, soup, salad, rice & noodles")
    source_name: str
    prep_minutes: int
    instructions: str = Field(description="Full, verbatim numbered steps (1., 2., 3.)")
    ingredients: list[Ingredient]


def get_gcs_bucket():
    bucket_name = st.secrets.get("GCS_BUCKET_NAME", "meal-planner-recipe")
    info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(info)
    client = storage.Client(credentials=credentials)
    return client.bucket(bucket_name)


def clean_html(html: str) -> str:
    text = re.sub(r'<(script|style|nav|footer|header)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()[:14000]


def parse_recipe(client, url: str) -> dict | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "sv-SE,sv;q=0.9",
    }
    resp = session.get(url, headers=headers, timeout=15, verify=False)
    resp.raise_for_status()
    page_text = clean_html(resp.text)

    prompt = f"""
    You are an expert Swedish recipe parser and data normalizer.
    URL: {url}
    Content:
    {page_text}

    RULES:
    1. title: Exact verbatim recipe title.
    2. protein: One of: chicken, beef, pork, fish, seafood, vegetarian, vegan.
    3. occasion: 'everyday', 'weekend', or 'guest'.
    4. category: One of: pasta, chicken, meat, fish, vegetarian, vegan, soup, salad, rice & noodles.
    5. instructions: Verbatim numbered steps (1., 2., 3.). Do not shorten.
    6. ingredients: Break down all ingredients. 
       - 'original_name': Exact text as written in the recipe.
       - 'normalized_name': Clean shopping name (e.g., 'Gul lök', 'Vispgrädde').
       - OMIT salt, pepper, oil, water, and rice entirely.
       - aisle: Must be one of: {", ".join(AISLES)}.
    7. source_name: Source website name.
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


def main():
    api_key = st.secrets.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    bucket = get_gcs_bucket()
    print(f"📦 Connected to GCS Bucket: {bucket.name}")

    blobs = list(bucket.list_blobs(prefix="recipes/"))
    json_blobs = [b for b in blobs if b.name.endswith(".json")]
    print(f"🔄 Found {len(json_blobs)} recipes in GCS to re-parse and fix.\n")

    updated = 0
    for blob in json_blobs:
        try:
            old_data = json.loads(blob.download_as_text(encoding="utf-8"))

            # 🚀 SMART SKIP: Check if this file already has the new schema
            ingredients = old_data.get("ingredients", [])
            if ingredients and "original_name" in ingredients[0]:
                print(f"⏩ Already updated, skipping: {blob.name}")
                continue

            url = old_data.get("url")
            if not url:
                print(f"  ⚠️ Skipping {blob.name} (No URL found inside JSON)")
                continue

            print(f"🔄 Fixing: {old_data.get('title', url)}")
            new_data = parse_recipe(client, url)
            if not new_data:
                continue

            # Determine correct path based on new protein classification
            slug = re.sub(r'[^a-zA-Z0-9åäöÅÄÖ]+', '-', new_data['title'].lower()).strip('-')
            protein = new_data.get('protein', 'other').lower()
            new_path = f"recipes/{protein}/{slug}.json"

            # Upload updated data
            new_blob = bucket.blob(new_path)
            new_blob.upload_from_string(
                json.dumps(new_data, ensure_ascii=False, indent=2),
                content_type="application/json"
            )

            # Delete old file if the protein category changed folder paths
            if blob.name != new_path:
                blob.delete()

            updated += 1
            print(f"  ✅ Fixed & Saved: {new_path}")
            
            time.sleep(5.0)  # Safe delay under 15 RPM free tier limit
        except Exception as e:
            print(f"  ❌ Failed to fix {blob.name}: {e}")


if __name__ == "__main__":
    main()