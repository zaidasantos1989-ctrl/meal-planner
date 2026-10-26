import json
from google.cloud import storage
from google.oauth2 import service_account
import streamlit as st

info = st.secrets["gcp_service_account"]
credentials = service_account.Credentials.from_service_account_info(info)
client = storage.Client(credentials=credentials)
bucket = client.bucket(
    st.secrets.get("GCS_BUCKET_NAME", "meal-planner-recipe")
)

SIDE_DISHES = [
    "potatismos",
    "stuvade-makaroner",
    "stuvade_makaroner",
    "stuvad-makaron",
    "bearnaise",
    "graddsas",
    "dressing",
    "vitloksbrod",
    "pommes",
    "sas-",
]

deleted = 0
updated = 0

for blob in bucket.list_blobs(prefix="recipes/"):
    name = blob.name.lower()

    # 1. Delete side dishes/accessories
    if any(side in name for side in SIDE_DISHES):
        print(f"🗑️ Deleting side dish: {blob.name}")
        blob.delete()
        deleted += 1
        continue

    # 2. Fix Pasta and Soup categories inside JSONs
    try:
        data = json.loads(blob.download_as_text())
        title = data.get("title", "").lower()
        changed = False

        if "soppa" in title and data.get("category") != "soup":
            data["category"] = "soup"
            changed = True
        elif (
            any(
                p in title
                for p in [
                    "pasta",
                    "spagetti",
                    "spaghetti",
                    "lasagne",
                    "penne",
                    "tagliatelle",
                ]
            )
            and data.get("category") != "pasta"
        ):
            data["category"] = "pasta"
            changed = True

        if changed:
            blob.upload_from_string(
                json.dumps(data, ensure_ascii=False, indent=2),
                content_type="application/json",
            )
            print(f"🔄 Fixed category for: {data['title']} -> {data['category']}")
            updated += 1
    except Exception:
        pass

print(
    f"\n✨ Done! Deleted {deleted} side dishes and fixed categories for {updated} recipes."
)