from datetime import date, datetime

from sqlalchemy import ForeignKey, Text, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DEFAULT_CATEGORIES = "pasta,chicken,meat,fish,vegetarian"

# ==============================================================================
# 🛒 EXACT AISLES IN YOUR REQUESTED ORDER
# ==============================================================================
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

EXCLUDED_INGREDIENTS = [
    "salt",
    "peppar",
    "svartpeppar",
    "vitpeppar",
    "nymalen svartpeppar",
    "olja",
    "olivolja",
    "rapsolja",
    "vatten",
]

TO_BASE = {"kg": ("g", 1000), "l": ("ml", 1000)}

SessionLocal = sessionmaker(expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profile"
    id: Mapped[int] = mapped_column(primary_key=True)
    people: Mapped[int]
    allergies: Mapped[str] = mapped_column(Text)
    dislikes: Mapped[str] = mapped_column(Text)
    preferences: Mapped[str] = mapped_column(Text)
    categories: Mapped[str] = mapped_column(Text)
    max_minutes: Mapped[int]


class MealPlan(Base):
    __tablename__ = "meal_plan"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime]
    start_date: Mapped[date]
    days: Mapped[int]
    meals: Mapped[list["Meal"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="Meal.day"
    )


class Meal(Base):
    __tablename__ = "meal"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("meal_plan.id", ondelete="CASCADE"))
    day: Mapped[int]
    meal_type: Mapped[str]
    title: Mapped[str]
    category: Mapped[str]
    prep_minutes: Mapped[int]
    instructions: Mapped[str] = mapped_column(Text)
    plan: Mapped[MealPlan] = relationship(back_populates="meals")
    ingredients: Mapped[list["Ingredient"]] = relationship(
        back_populates="meal", cascade="all, delete-orphan"
    )


class Ingredient(Base):
    __tablename__ = "ingredient"
    id: Mapped[int] = mapped_column(primary_key=True)
    meal_id: Mapped[int] = mapped_column(ForeignKey("meal.id", ondelete="CASCADE"))
    name: Mapped[str]
    quantity: Mapped[float]
    unit: Mapped[str]
    aisle: Mapped[str]
    meal: Mapped[Meal] = relationship(back_populates="ingredients")


class GroceryItem(Base):
    __tablename__ = "grocery_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    amount: Mapped[str]
    aisle: Mapped[str]
    source: Mapped[str]  # "plan" or "custom"
    checked: Mapped[bool]


def init_db(url: str) -> None:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    SessionLocal.configure(bind=engine)


def get_profile(s) -> Profile:
    p = s.get(Profile, 1)
    if p is None:
        p = Profile(id=1, people=2, allergies="", dislikes="", preferences="",
                    categories=DEFAULT_CATEGORIES, max_minutes=45)
        s.add(p)
        s.commit()
    return p


def latest_plan(s) -> MealPlan | None:
    return s.scalars(select(MealPlan).order_by(MealPlan.id.desc()).limit(1)).first()


def classify_aisle(name: str) -> str:
    """Strictly maps ingredients into your requested categories."""
    n = name.lower()
    if any(w in n for w in ["tandkräm", "schampo", "duschtvål", "tvål", "handtvål", "toalettpapper", "hushållspapper", "wc-rent", "rengöring", "toalettrengöring"]):
        return "Badrums artiklar"
    if any(w in n for w in ["pinsa", "hamburgerbröd", "korvbröd", "bröd", "tortilla", "pita", "naan", "tunnbröd"]):
        return "Bröd"
    if any(w in n for w in ["ost", "parmesan", "feta", "mozzarella", "halloumi", "kaviar", "grillkorv", "falukorv", "leverpastej", "skinka", "salami"]):
        return "Ost och annat"
    if any(w in n for w in ["färs", "nötfärs", "fläskfärs", "blandfärs", "biff", "oxfilé", "fläskfilé", "högrev", "entrecote", "fläskkarré", "kött", "fläskkött", "nötkött", "bacon"]):
        return "Kött"
    if any(w in n for w in ["frukt", "grönt", "lök", "vitlök", "tomat", "paprika", "banan", "potatis", "morot", "spenat", "sallad", "citron", "dill", "persilja", "gurka", "zucchini", "broccoli", "avokado", "äpple", "champinjoner", "svamp"]):
        return "Frukt och grönt"
    if any(w in n for w in ["kyckling", "fisk", "lax", "torsk", "röding", "sej", "räkor", "glass", "frysta bär", "ärtor"]):
        return "Fryst"
    if any(w in n for w in ["mjölk", "grädde", "vispgrädde", "matlagningsgrädde", "crème fraiche", "creme fraiche", "gräddfil", "smör", "keso", "kvarg", "fil", "yoghurt"]):
        return "Mejeri"
    if any(w in n for w in ["chips", "godis", "choklad", "lösgodis", "snacks"]):
        return "Chips och godis"
    if any(w in n for w in ["pasta", "spagetti", "spaghetti", "lasagne", "penne", "ris", "bulgur", "couscous", "krossade tomater", "tomatpuré", "sås", "soja", "vinäger", "olja", "krydda", "buljong", "fond", "mjöl", "socker"]):
        return "Skafferi"
    return "Övrigt"


def _ingredients(items) -> list[Ingredient]:
    res = []
    for i in items:
        name = (i.name or "").strip()
        # Exclude salt, pepper, oil from grocery list
        if any(ex in name.lower() for ex in EXCLUDED_INGREDIENTS):
            continue
        aisle = classify_aisle(name)
        res.append(Ingredient(name=name, quantity=i.quantity or 0, unit=(i.unit or "").strip(),
                              aisle=aisle))
    return res


def save_plan(s, start: date, days: int, plan_out) -> MealPlan:
    plan = MealPlan(created_at=datetime.now(), start_date=start, days=days)
    for m in plan_out.meals:
        plan.meals.append(Meal(
            day=m.day, meal_type=m.meal_type.lower(), title=m.title, category=m.category.lower(),
            prep_minutes=m.prep_minutes, instructions=m.instructions,
            ingredients=_ingredients(m.ingredients),
        ))
    s.add(plan)
    s.commit()
    return plan


def replace_meal(s, meal: Meal, new) -> None:
    meal.title = new.title
    meal.category = new.category.lower()
    meal.prep_minutes = new.prep_minutes
    meal.instructions = new.instructions
    meal.ingredients.clear()
    meal.ingredients.extend(_ingredients(new.ingredients))
    s.commit()


def fmt_amount(quantity: float, unit: str) -> str:
    if not quantity:
        return unit or ""
    if unit in ("g", "ml") and quantity >= 1000:
        quantity, unit = quantity / 1000, {"g": "kg", "ml": "l"}[unit]
    return f"{round(quantity, 2):g} {unit}".strip()


def rebuild_grocery_list(s, plan: MealPlan) -> None:
    """Replace plan-based items with merged ingredients; keep custom items and ticks."""
    old = s.scalars(select(GroceryItem).where(GroceryItem.source == "plan")).all()
    was_checked = {i.name.lower() for i in old if i.checked}
    s.execute(delete(GroceryItem).where(GroceryItem.source == "plan"))

    totals: dict[tuple[str, str, str], dict] = {}
    for meal in plan.meals:
        for ing in meal.ingredients:
            name = (ing.name or "").strip()
            if any(ex in name.lower() for ex in EXCLUDED_INGREDIENTS):
                continue
            unit, qty = (ing.unit or "").lower(), ing.quantity or 0
            if unit in TO_BASE:
                unit, factor = TO_BASE[unit]
                qty *= factor
            norm_name = name.lower()
            aisle = ing.aisle
            entry = totals.setdefault((norm_name, unit, aisle), {"qty": 0.0, "display_name": name})
            entry["qty"] += qty

    for (norm_name, unit, aisle), e in totals.items():
        s.add(GroceryItem(name=e["display_name"].capitalize(), amount=fmt_amount(e["qty"], unit),
                          aisle=aisle, source="plan", checked=norm_name in was_checked))
    s.commit()


def grocery_items(s) -> list[GroceryItem]:
    items = s.scalars(select(GroceryItem)).all()
    aisle_order = {aisle: idx for idx, aisle in enumerate(AISLES)}
    return sorted(items, key=lambda x: (aisle_order.get(x.aisle, 99), x.name))