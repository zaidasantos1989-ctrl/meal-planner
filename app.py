import os

# Temporarily remove proxy settings for this Python script only (work computer safe)
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("ALL_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

from datetime import date, timedelta
import hmac
import json
import re
from urllib.parse import quote_plus
import agent
import db
from db import GroceryItem
from sqlalchemy import delete, update
import streamlit as st

st.set_page_config(page_title="Meal Planner", page_icon="🍽️")

# ----------------- UI Translations -----------------
T = {
    "English": {
        "title": "🍽️ Meal Planner",
        "household_pw": "Household password",
        "wrong_pw": "Wrong password",
        "no_api_key": "Add GEMINI_API_KEY to .streamlit/secrets.toml to generate plans.",
        "tabs": ["📅 Plan", "🛒 Groceries", "⚙️ Settings"],
        # Theme
        "theme_label": "Theme",
        "theme_light": "☀️ Light",
        "theme_dark": "🌙 Dark",
        # Plan
        "new_plan": "✨ New plan",
        "start_date": "Start date",
        "length": "Length",
        "1_week": "1 week",
        "2_weeks": "2 weeks",
        "meals_per_day": "Meals per day",
        "meal_lunch": "lunch",
        "meal_dinner": "dinner",
        "special_note": "Anything special this time?",
        "note_placeholder": "e.g. guests on Saturday, use up the spinach",
        "generate_btn": "Generate plan",
        "planning_status": "Planning your meals…",
        "attempt_issues": "Attempt {attempt}: found {count} issue(s), asking for a fix…",
        "attempt_pass": "Attempt {attempt}: all checks passed ✅",
        "plan_failed": "Something went wrong",
        "plan_ready": "Plan ready!",
        "no_plan_yet": "No plan yet. Open **✨ New plan** above.",
        "ingredients": "Ingredients",
        "steps": "Steps",
        "swap_for": "Swap for a…",
        "swap_btn": "🔄 Swap this meal",
        "swapping_spinner": "Finding something else…",
        # Week salad
        "weekly_salad_title": "🥗 Weekly Batch Salad",
        "weekly_salad_desc": "Prep once on Day 1. Keeps crunchy in the fridge all week as a side for lunches and dinners.",
        "gen_new_salad": "🔄 Generate new salad recipe",
        "add_salad_groceries": "🛒 Add salad ingredients to grocery list",
        "salad_added_groceries": "Salad ingredients added to groceries! ✅",
        # Groceries
        "add_item": "Add your own item",
        "item_placeholder": "e.g. coffee, toilet paper",
        "amount": "Amount (optional)",
        "amount_placeholder": "e.g. 2 packs",
        "aisle": "Aisle",
        "add_btn": "➕ Add",
        "list_empty": "Your list is empty. Generate a plan or add items above.",
        "items_left": "{left} of {total} items left · ✍️ = added by you",
        "remove_bought": "🧹 Remove bought items",
        "uncheck_all": "↩️ Uncheck all",
        "share_list": "📋 Copy / share list",
        "download_txt": "Download .txt",
        # Settings
        "how_many_people": "How many people?",
        "allergies": "Allergies (comma separated)",
        "allergies_placeholder": "e.g. nuts, shellfish, gluten",
        "dislikes": "Dislikes",
        "dislikes_placeholder": "e.g. mushrooms, olives",
        "preferences": "Preferences",
        "pref_placeholder": "e.g. kid-friendly, Mediterranean, not too spicy",
        "rotate_between": "Rotate between",
        "max_cooking_time": "Max cooking time (minutes)",
        "save_btn": "Save",
        "pick_one_cat": "Pick at least one category.",
        "saved_ok": "Saved ✅",
        # AI Language Prompting
        "ai_lang_instruction": (
            "Source & Recipe Rules:\n"
            "1. Pick only established recipes from Köket.se, ICA.se, Arla.se, Coop.se, Tasteline, or Zeinas Kitchen.\n"
            "2. Mention the source at the end of instructions (e.g. 'Source: Köket.se'). Do not invent fake URLs.\n"
            "3. Always add the chosen carb side directly into the ingredients list.\n"
            "4. Format instructions strictly as numbered steps (1., 2., 3.)."
        ),
    },
    "Svenska": {
        "title": "🍽️ Måltidsplanerare",
        "household_pw": "Lösenord för hushållet",
        "wrong_pw": "Fel lösenord",
        "no_api_key": "Lägg till GEMINI_API_KEY i .streamlit/secrets.toml för att skapa planer.",
        "tabs": ["📅 Måltidsplan", "🛒 Inköpslista", "⚙️ Inställningar"],
        # Theme
        "theme_label": "Tema",
        "theme_light": "☀️ Ljust",
        "theme_dark": "🌙 Mörkt",
        # Plan
        "new_plan": "✨ Ny måltidsplan",
        "start_date": "Startdatum",
        "length": "Längd",
        "1_week": "1 vecka",
        "2_weeks": "2 veckor",
        "meals_per_day": "Måltider per dag",
        "meal_lunch": "lunch",
        "meal_dinner": "middag",
        "special_note": "Något särskilt den här gången?",
        "note_placeholder": "t.ex. gäster på lördag, använd upp spenaten",
        "generate_btn": "Skapa måltidsplan",
        "planning_status": "Planerar dina måltider…",
        "attempt_issues": "Försök {attempt}: hittade {count} problem, ber om korrigering…",
        "attempt_pass": "Försök {attempt}: alla kontroller godkända ✅",
        "plan_failed": "Något gick fel",
        "plan_ready": "Planen är klar!",
        "no_plan_yet": "Ingen måltidsplan än. Öppna **✨ Ny måltidsplan** ovan.",
        "ingredients": "Ingredienser",
        "steps": "Instruktioner",
        "swap_for": "Byt mot en…",
        "swap_btn": "🔄 Byt ut denna måltid",
        "swapping_spinner": "Hittar ett annat alternativ…",
        # Veckosallad
        "weekly_salad_title": "🥗 Veckosallad",
        "weekly_salad_desc": "Gör en stor sats på söndag/måndag. Håller sig krispig i kylen hela veckan som tillbehör.",
        "gen_new_salad": "🔄 Skapa nytt recept på veckosallad",
        "add_salad_groceries": "🛒 Lägg till ingredienser i inköpslistan",
        "salad_added_groceries": "Salladsingredienser tillagda i inköpslistan! ✅",
        # Groceries
        "add_item": "Lägg till egen vara",
        "item_placeholder": "t.ex. kaffe, toalettpapper",
        "amount": "Mängd (valfritt)",
        "amount_placeholder": "t.ex. 2 paket",
        "aisle": "Kategori / Hylla",
        "add_btn": "➕ Lägg till",
        "list_empty": "Din lista är tom. Skapa en måltidsplan eller lägg till varor ovan.",
        "items_left": "{left} av {total} varor kvar · ✍️ = tillagd av dig",
        "remove_bought": "🧹 Ta bort köpta varor",
        "uncheck_all": "↩️ Avmarkera alla",
        "share_list": "📋 Kopiera / dela lista",
        "download_txt": "Ladda ner .txt",
        # Settings
        "how_many_people": "Hur många personer?",
        "allergies": "Allergier (kommaseparerade)",
        "allergies_placeholder": "t.ex. nötter, skaldjur, gluten",
        "dislikes": "Ogillar",
        "dislikes_placeholder": "t.ex. svamp, oliver",
        "preferences": "Önskemål & preferenser",
        "pref_placeholder": "t.ex. barnvänligt, husmanskost, medelhavsmat",
        "rotate_between": "Rotera mellan",
        "max_cooking_time": "Max tillagningstid (minuter)",
        "save_btn": "Spara",
        "pick_one_cat": "Välj minst en kategori.",
        "saved_ok": "Sparat ✅",
        # AI Language Prompting
        "ai_lang_instruction": (
            "Käll- och receptregler:\n"
            "1. Välj endast beprövade recept från Köket.se, ICA.se, Arla.se, Coop.se, Tasteline eller Zeinas Kitchen.\n"
            "2. Ange källans namn i slutet av instruktionerna (t.ex. 'Källa: Köket.se'). Skriv inte ut fiktiva webbadresser.\n"
            "3. Lägg alltid till det valda kolhydrattillbehöret i ingredienslistan.\n"
            "4. Dela upp instruktionerna strikt i numrerade steg (1., 2., 3.)."
        ),
    },
}

# ----------------- Category & Aisle Display Translations -----------------
EMOJI = {
    "pasta": "🍝",
    "chicken": "🍗",
    "meat": "🥩",
    "fish": "🐟",
    "vegetarian": "🥦",
    "vegan": "🌱",
    "soup": "🍲",
    "salad": "🥗",
    "rice & noodles": "🍜",
}

CATEGORY_NAMES = {
    "English": {
        "pasta": "Pasta",
        "chicken": "Chicken",
        "meat": "Meat",
        "fish": "Fish",
        "vegetarian": "Vegetarian",
        "vegan": "Vegan",
        "soup": "Soup",
        "salad": "Salad",
        "rice & noodles": "Rice & Noodles",
    },
    "Svenska": {
        "pasta": "Pasta",
        "chicken": "Kyckling",
        "meat": "Kött",
        "fish": "Fisk",
        "vegetarian": "Vegetariskt",
        "vegan": "Veganskt",
        "soup": "Soppa",
        "salad": "Sallad",
        "rice & noodles": "Ris & nudlar",
    },
}


def fmt_category(cat: str, language: str) -> str:
    emoji = EMOJI.get(cat, "🍽️")
    name = CATEGORY_NAMES.get(language, {}).get(cat, cat.title())
    return f"{emoji} {name}"


AISLE_NAMES = {
    "English": {
        "Produce": "🥦 Produce",
        "Meat & Seafood": "🥩 Meat & Seafood",
        "Meat": "🥩 Meat",
        "Poultry": "🍗 Poultry",
        "Dairy": "🧀 Dairy",
        "Dairy & Eggs": "🧀 Dairy & Eggs",
        "Bakery": "🍞 Bakery",
        "Pantry": "🥫 Pantry",
        "Spices & Seasonings": "🧂 Spices & Seasonings",
        "Frozen": "🧊 Frozen",
        "Canned Goods": "🥫 Canned Goods",
        "Grains & Pasta": "🍝 Grains & Pasta",
        "Other": "🛒 Other",
    },
    "Svenska": {
        "Produce": "🥦 Frukt & Grönt",
        "Meat & Seafood": "🥩 Kött & Fisk",
        "Meat": "🥩 Kött & Chark",
        "Poultry": "🍗 Fågel / Kyckling",
        "Dairy": "🧀 Mejeri",
        "Dairy & Eggs": "🧀 Mejeri & Ägg",
        "Bakery": "🍞 Bröd & Bageri",
        "Pantry": "🥫 Skafferi",
        "Spices & Seasonings": "🧂 Kryddor & Smaksättning",
        "Frozen": "🧊 Fryst",
        "Canned Goods": "🥫 Konserver",
        "Grains & Pasta": "🍝 Ris, Pasta & Gryn",
        "Other": "🛒 Övrigt",
    },
}


def fmt_aisle(aisle: str, language: str) -> str:
    return AISLE_NAMES.get(language, {}).get(aisle, aisle)


# Swedish date formatting helper
WEEKDAYS_SV = [
    "Måndag",
    "Tisdag",
    "Onsdag",
    "Torsdag",
    "Fredag",
    "Lördag",
    "Söndag",
]
MONTHS_SV = [
    "jan",
    "feb",
    "mar",
    "apr",
    "maj",
    "jun",
    "jul",
    "aug",
    "sep",
    "okt",
    "nov",
    "dec",
]


def format_day_date(d: date, lang: str) -> str:
    if lang == "Svenska":
        return f"{WEEKDAYS_SV[d.weekday()]} {d.day} {MONTHS_SV[d.month - 1]}"
    return d.strftime("%A %d %b")


# Language selection in sidebar (Svenska as default)
lang = st.sidebar.selectbox(
    "🌐 Språk / Language", ["Svenska", "English"], index=0
)
t = T[lang]

# ----------------- Theme Switcher -----------------
theme_mode = st.sidebar.radio(
    f"🎨 {t['theme_label']}",
    options=["light", "dark"],
    format_func=lambda x: t["theme_light"] if x == "light" else t["theme_dark"],
    horizontal=True,
    index=0,
)

if theme_mode == "dark":
    dark_css = """
    <style>
        .stApp, header[data-testid="stHeader"] {
            background-color: #0e1117 !important;
            color: #fafafa !important;
        }
        section[data-testid="stSidebar"] {
            background-color: #161b22 !important;
        }
        .streamlit-expanderHeader {
            background-color: #1f242c !important;
            color: #fafafa !important;
            border-radius: 8px !important;
        }
        div[data-testid="stExpander"] {
            border: 1px solid #30363d !important;
            border-radius: 8px !important;
        }
        input, textarea, select, div[data-baseweb="select"] {
            background-color: #21262d !important;
            color: #fafafa !important;
            border-color: #30363d !important;
        }
        button[data-baseweb="tab"] {
            color: #8b949e !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            color: #58a6ff !important;
            border-bottom-color: #58a6ff !important;
        }
    </style>
    """
    st.markdown(dark_css, unsafe_allow_html=True)
else:
    light_css = """
    <style>
        .stApp, header[data-testid="stHeader"] {
            background-color: #f8f9fa !important;
            color: #1a1a1a !important;
        }
        section[data-testid="stSidebar"] {
            background-color: #ffffff !important;
        }
        .streamlit-expanderHeader {
            background-color: #ffffff !important;
            color: #1a1a1a !important;
            border-radius: 8px !important;
        }
        div[data-testid="stExpander"] {
            border: 1px solid #e1e4e8 !important;
            border-radius: 8px !important;
        }
    </style>
    """
    st.markdown(light_css, unsafe_allow_html=True)


# ----------------- Step & Recipe Helpers -----------------
def extract_recipe_url(text: str) -> str | None:
    """Extracts the direct recipe URL from the instructions if present."""
    if not text:
        return None
    # Look for full web links (http or https)
    match = re.search(r"(https?://[^\s\)\>\]]+)", text)
    return match.group(1).rstrip(".,;") if match else None

def format_steps(text: str) -> str:
    """Formats steps into a clean numbered list while preserving links."""
    if not text:
        return ""
    # Ensure step numbers start on separate lines with empty space
    formatted = re.sub(r"(?<!\n)(\b\d+[\.\)])\s*", r"\n\1 ", text)
    lines = [line.strip() for line in formatted.splitlines() if line.strip()]
    return "\n\n".join(lines)

def cfg(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


def setup() -> bool:
    db.init_db(cfg("DATABASE_URL", "sqlite:///meal_planner.db"))
    return True


def require_password() -> None:
    expected = cfg("APP_PASSWORD")
    if not expected or st.session_state.get("authed"):
        return
    st.title(t["title"])
    pw = st.text_input(t["household_pw"], type="password")
    if pw and hmac.compare_digest(pw, expected):
        st.session_state.authed = True
        st.rerun()
    if pw:
        st.error(t["wrong_pw"])
    st.stop()


def toggle_item(item_id: int) -> None:
    with db.SessionLocal() as s:
        item = s.get(GroceryItem, item_id)
        if item:
            item.checked = not item.checked
            s.commit()


# ----------------- Weekly Salad Helpers -----------------
SALAD_FILE = ".weekly_salad.json"


def get_weekly_salad(language: str) -> dict:
    if os.path.exists(SALAD_FILE):
        try:
            with open(SALAD_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    if language == "Svenska":
        return {
            "title": "Klassisk Veckosallad",
            "ingredients": [
                {"name": "Vitkål", "amount": "1 kg"},
                {"name": "Morötter", "amount": "3 st"},
                {"name": "Röd paprika", "amount": "1 st"},
                {"name": "Rapsolja", "amount": "1/2 dl"},
                {"name": "Äppelcidervinäger", "amount": "1/2 dl"},
                {
                    "name": "Italiensk salladskrydda / Salt & peppar",
                    "amount": "1 msk",
                },
            ],
            "instructions": (
                "1. Strimla vitkålen fint (gärna med osthyvel) och grovriv morötterna.\n"
                "2. Finhacka paprikan.\n"
                "3. Koka upp olja, vinäger, vatten och kryddor i en liten kastrull.\n"
                "4. Slå den varma dressingen över grönsakerna och blanda ordentligt.\n"
                "5. Låt svalna och förvara i en tät glasburk i kylen. Håller i 1-2 veckor!"
            ),
        }
    else:
        return {
            "title": "Classic Weekly Cabbage Salad",
            "ingredients": [
                {"name": "White cabbage", "amount": "1 kg"},
                {"name": "Carrots", "amount": "3 pcs"},
                {"name": "Red bell pepper", "amount": "1 pc"},
                {"name": "Rapeseed oil", "amount": "1/2 dl"},
                {"name": "Apple cider vinegar", "amount": "1/2 dl"},
                {"name": "Salad herbs / salt & pepper", "amount": "1 tbsp"},
            ],
            "instructions": (
                "1. Finely shred the cabbage and coarsely grate the carrots.\n"
                "2. Finely dice the bell pepper.\n"
                "3. In a small pot, briefly boil oil, vinegar, and seasoning.\n"
                "4. Pour the warm dressing over the vegetables and toss thoroughly.\n"
                "5. Store in an airtight container in the fridge. Lasts 1-2 weeks!"
            ),
        }


def generate_ai_salad(api_key: str, model_name: str, language: str) -> dict:
    from google import genai

    client = genai.Client(api_key=api_key)

    prompt = (
        f"Generate a batch-prep 'Weekly Salad' (Veckosallad) meant to be prepared once and stay crunchy in an airtight container in the fridge for 7 days. "
        f"Language MUST be strictly {language}. "
        "Return ONLY a JSON object with keys:\n"
        "- 'title': name of the salad\n"
        "- 'ingredients': list of objects with 'name' and 'amount'\n"
        "- 'instructions': string with numbered steps (1., 2., 3.) separated by line breaks."
    )

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    data = json.loads(response.text)
    with open(SALAD_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


setup()
require_password()

API_KEY = cfg("GEMINI_API_KEY")
MODEL = cfg("GEMINI_MODEL", "gemini-3.5-flash-lite")

st.title(t["title"])
if not API_KEY:
    st.warning(t["no_api_key"])

tab_plan, tab_grocery, tab_settings = st.tabs(t["tabs"])

# ---------------- Plan ----------------
with tab_plan, db.SessionLocal() as s:
    profile = db.get_profile(s)
    plan = db.latest_plan(s)

    with st.expander(t["new_plan"], expanded=plan is None):
        today = date.today()
        start = st.date_input(
            t["start_date"], today + timedelta(days=(7 - today.weekday()) % 7)
        )
        days = st.radio(
            t["length"],
            [7, 14],
            horizontal=True,
            format_func=lambda d: t["1_week"] if d == 7 else t["2_weeks"],
        )

        meal_types = st.multiselect(
            t["meals_per_day"],
            ["lunch", "dinner"],
            default=["dinner"],
            format_func=lambda m: t["meal_lunch"]
            if m == "lunch"
            else t["meal_dinner"],
        )
        note = st.text_input(t["special_note"], placeholder=t["note_placeholder"])

        if st.button(
            t["generate_btn"],
            type="primary",
            disabled=not (API_KEY and meal_types),
        ):
            with st.status(t["planning_status"], expanded=True) as status:

                def on_step(attempt, problems):
                    if problems:
                        st.write(
                            t["attempt_issues"].format(
                                attempt=attempt, count=len(problems)
                            )
                        )
                    else:
                        st.write(t["attempt_pass"].format(attempt=attempt))

                # Inject language instruction into note
                full_note = (
                    f"{note}. {t['ai_lang_instruction']}"
                    if note
                    else t["ai_lang_instruction"]
                )

                try:
                    result, problems = agent.plan_meals(
                        profile,
                        start,
                        days,
                        meal_types,
                        full_note,
                        API_KEY,
                        MODEL,
                        on_step,
                        language=lang,
                    )
                except Exception as e:
                    status.update(label=t["plan_failed"], state="error")
                    st.error(f"AI request failed: {e}")
                    st.stop()
                plan = db.save_plan(s, start, days, result)
                db.rebuild_grocery_list(s, plan)
                status.update(label=t["plan_ready"], state="complete")
            st.session_state.plan_warnings = problems
            st.rerun()

    for w in st.session_state.pop("plan_warnings", []):
        st.warning(f"⚠️ Please double-check: {w}")

    if plan is None:
        st.info(t["no_plan_yet"])
    else:
        # ---------------- 🥗 Weekly Salad Card ----------------
        salad = get_weekly_salad(lang)
        with st.expander(
            f"{t['weekly_salad_title']}: {salad['title']}", expanded=False
        ):
            st.caption(t["weekly_salad_desc"])
            st.markdown(f"**{t['ingredients']}**")
            st.markdown(
                "\n".join(
                    f"- {i['amount']} {i['name']}"
                    for i in salad.get("ingredients", [])
                )
            )
            st.markdown(f"**{t['steps']}**")
            st.markdown(format_steps(salad.get("instructions", "")))

            col_s1, col_s2 = st.columns(2)
            if col_s1.button(t["add_salad_groceries"]):
                for ing in salad.get("ingredients", []):
                    s.add(
                        GroceryItem(
                            name=ing["name"],
                            amount=ing.get("amount", ""),
                            aisle="Produce"
                            if "Produce" in db.AISLES
                            else db.AISLES[0],
                            source="custom",
                            checked=False,
                        )
                    )
                s.commit()
                st.success(t["salad_added_groceries"])

            if col_s2.button(t["gen_new_salad"], disabled=not API_KEY):
                with st.spinner(
                    "Skapar sallad..."
                    if lang == "Svenska"
                    else "Crafting salad..."
                ):
                    try:
                        salad = generate_ai_salad(API_KEY, MODEL, lang)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
        st.divider()

        categories = [c for c in profile.categories.split(",") if c]
        by_day: dict[int, list] = {}
        for m in plan.meals:
            by_day.setdefault(m.day, []).append(m)

        for d in range(1, plan.days + 1):
            day_date = plan.start_date + timedelta(days=d - 1)
            st.subheader(format_day_date(day_date, lang))

            for m in sorted(
                by_day.get(d, []), key=lambda m: m.meal_type != "lunch"
            ):
                meal_display_type = (
                    t["meal_lunch"].title()
                    if m.meal_type == "lunch"
                    else t["meal_dinner"].title()
                )
                header = f"{EMOJI.get(m.category, '🍽️')} {meal_display_type}: {m.title} · {m.prep_minutes} min"
                with st.expander(header):
                    st.markdown(f"**{t['ingredients']}**")
                    st.markdown(
                        "\n".join(
                            f"- {db.fmt_amount(i.quantity, i.unit)} {i.name}"
                            for i in m.ingredients
                        )
                    )
                    st.markdown(f"**{t['steps']}**")

                    # 1. Display full verbatim steps and any inline source link
                    st.markdown(format_steps(m.instructions))

                    # 2. Extract and display the direct source button
                    direct_url = extract_recipe_url(m.instructions)
                    if direct_url:
                        btn_label = (
                            "📖 Öppna originalreceptet på källsajten ↗"
                            if lang == "Svenska"
                            else "📖 Open original recipe on source website ↗"
                        )
                        st.link_button(btn_label, direct_url)
                    else:
                        # Fallback search if no URL was present in instructions
                        q = quote_plus(m.title)
                        st.link_button(
                            "🔍 Sök originalreceptet ↗"
                            if lang == "Svenska"
                            else "🔍 Search recipe ↗",
                            f"https://www.google.com/search?q=recept+{q}",
                        )

                    options = list(dict.fromkeys(categories + [m.category]))
                    # Categories translated with format_func
                    cat = st.selectbox(
                        t["swap_for"],
                        options,
                        index=options.index(m.category),
                        key=f"cat_{m.id}",
                        format_func=lambda c: fmt_category(c, lang),
                    )
                    if st.button(
                        t["swap_btn"], key=f"swap_{m.id}", disabled=not API_KEY
                    ):
                        with st.spinner(t["swapping_spinner"]):
                            try:
                                original_prefs = profile.preferences
                                profile.preferences = (
                                    f"{original_prefs}. {t['ai_lang_instruction']}"
                                )
                                new, problems = agent.swap_meal(
                                    profile,
                                    m.day,
                                    m.meal_type,
                                    cat,
                                    [x.title for x in plan.meals],
                                    API_KEY,
                                    MODEL,
                                    language=lang,
                                )
                                profile.preferences = original_prefs
                            except Exception as e:
                                st.error(f"AI request failed: {e}")
                                st.stop()
                        db.replace_meal(s, m, new)
                        db.rebuild_grocery_list(s, plan)
                        st.session_state.plan_warnings = problems
                        st.rerun()

# ---------------- Groceries ----------------
with tab_grocery, db.SessionLocal() as s:
    with st.form("add_item", clear_on_submit=True):
        name = st.text_input(t["add_item"], placeholder=t["item_placeholder"])
        c1, c2 = st.columns(2)
        amount = c1.text_input(t["amount"], placeholder=t["amount_placeholder"])
        other_idx = db.AISLES.index("Other") if "Other" in db.AISLES else 0
        # Aisle translated with format_func
        aisle = c2.selectbox(
            t["aisle"],
            db.AISLES,
            index=other_idx,
            format_func=lambda a: fmt_aisle(a, lang),
        )
        if st.form_submit_button(t["add_btn"]) and name.strip():
            s.add(
                GroceryItem(
                    name=name.strip(),
                    amount=amount.strip(),
                    aisle=aisle,
                    source="custom",
                    checked=False,
                )
            )
            s.commit()

    items = db.grocery_items(s)
    if not items:
        st.info(t["list_empty"])
    else:
        left_count = sum(not i.checked for i in items)
        st.caption(t["items_left"].format(left=left_count, total=len(items)))

        # Group and display by translated aisle name
        for aisle in db.AISLES:
            group = [i for i in items if i.aisle == aisle]
            if not group:
                continue
            st.markdown(f"**{fmt_aisle(aisle, lang)}**")
            for i in group:
                label = f"{i.name} — {i.amount}" if i.amount else i.name
                if i.source == "custom":
                    label += " ✍️"
                st.checkbox(
                    f"~~{label}~~" if i.checked else label,
                    value=i.checked,
                    key=f"gi_{i.id}",
                    on_change=toggle_item,
                    args=(i.id,),
                )

        c1, c2 = st.columns(2)
        if c1.button(t["remove_bought"]):
            s.execute(delete(GroceryItem).where(GroceryItem.checked.is_(True)))
            s.commit()
            st.rerun()
        if c2.button(t["uncheck_all"]):
            s.execute(update(GroceryItem).values(checked=False))
            s.commit()
            for k in [k for k in st.session_state if str(k).startswith("gi_")]:
                del st.session_state[k]
            st.rerun()

        # Build share text with translated headers
        lines = []
        for a in db.AISLES:
            group = [i for i in items if i.aisle == a]
            if not group:
                continue
            lines.append(f"\n--- {fmt_aisle(a, lang)} ---")
            for i in group:
                lines.append(
                    f"[{'x' if i.checked else ' '}] {i.name}"
                    + (f" — {i.amount}" if i.amount else "")
                )
        text = "\n".join(lines).strip()

        with st.expander(t["share_list"]):
            st.code(text, language=None)
            st.download_button(
                t["download_txt"], text, file_name="grocery-list.txt"
            )

# ---------------- Settings ----------------
with tab_settings, db.SessionLocal() as s:
    p = db.get_profile(s)
    with st.form("profile"):
        people = st.number_input(t["how_many_people"], 1, 12, p.people)
        allergies = st.text_input(
            t["allergies"], p.allergies, placeholder=t["allergies_placeholder"]
        )
        dislikes = st.text_input(
            t["dislikes"], p.dislikes, placeholder=t["dislikes_placeholder"]
        )
        preferences = st.text_area(
            t["preferences"], p.preferences, placeholder=t["pref_placeholder"]
        )
        current = [
            c for c in p.categories.split(",") if c in agent.ALL_CATEGORIES
        ]
        # Categories translated with format_func
        categories = st.multiselect(
            t["rotate_between"],
            agent.ALL_CATEGORIES,
            default=current,
            format_func=lambda c: fmt_category(c, lang),
        )
        max_minutes = st.slider(
            t["max_cooking_time"], 15, 120, p.max_minutes, step=5
        )
        if st.form_submit_button(t["save_btn"], type="primary"):
            if not categories:
                st.error(t["pick_one_cat"])
            else:
                p.people, p.allergies, p.dislikes = (
                    int(people),
                    allergies.strip(),
                    dislikes.strip(),
                )
                p.preferences, p.categories, p.max_minutes = (
                    preferences.strip(),
                    ",".join(categories),
                    max_minutes,
                )
                s.commit()
                st.success(t["saved_ok"])