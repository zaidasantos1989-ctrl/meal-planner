from datetime import date, datetime
from sqlalchemy import ForeignKey, Text, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DEFAULT_CATEGORIES = "pasta,chicken,meat,fish"

# Only the structural list of allowed categories in order
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
    name: Mapped[str]          # Original name for recipe cooking card
    shopping_name: Mapped[str] # AI-normalized clean name for grocery list
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


def _ingredients(items) -> list[Ingredient]:
    """Dynamically reads original and AI-normalized names directly from harvested data."""
    res = []
    for i in items:
        # 1. Original text for the cooking card
        raw_name = getattr(i, "original_name", None) or getattr(i, "name", "")
        # 2. Clean AI-normalized name for the grocery shopping list
        clean_name = getattr(i, "normalized_name", None) or raw_name
        
        raw_aisle = getattr(i, "aisle", "Övrigt")
        aisle = raw_aisle if raw_aisle in AISLES else "Övrigt"

        res.append(Ingredient(
            name=raw_name.strip(),
            shopping_name=clean_name.strip().capitalize(),
            quantity=i.quantity or 0,
            unit=(i.unit or "").strip(),
            aisle=aisle
        ))
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
    """Aggregates and sums up items using the AI-generated shopping names."""
    old = s.scalars(select(GroceryItem).where(GroceryItem.source == "plan")).all()
    was_checked = {i.name.lower() for i in old if i.checked}
    s.execute(delete(GroceryItem).where(GroceryItem.source == "plan"))

    totals: dict[tuple[str, str], dict] = {}
    for meal in plan.meals:
        for ing in meal.ingredients:
            # Uses the AI-normalized shopping name directly
            clean_name = (ing.shopping_name or ing.name or "").strip().capitalize()
            unit, qty = (ing.unit or "").lower(), ing.quantity or 0

            if unit in TO_BASE:
                unit, factor = TO_BASE[unit]
                qty *= factor

            aisle = ing.aisle
            key = (clean_name.lower(), aisle)

            # Sum quantities for identical items
            found = False
            for entry in totals.setdefault(key, []):
                if entry["unit"] == unit or not entry["unit"] or not unit:
                    if not entry["unit"] and unit:
                        entry["unit"] = unit
                    entry["qty"] += qty
                    found = True
                    break
            if not found:
                totals.setdefault(key, []).append({
                    "display_name": clean_name,
                    "unit": unit,
                    "qty": qty
                })

    for (norm_name, aisle), entries in totals.items():
        for e in entries:
            qty = e["qty"]
            unit = e["unit"]
            amount = fmt_amount(qty, unit) if (qty > 0 or unit) else ""

            s.add(GroceryItem(
                name=e["display_name"], 
                amount=amount,
                aisle=aisle, 
                source="plan", 
                checked=norm_name in was_checked
            ))
    s.commit()


def grocery_items(s) -> list[GroceryItem]:
    items = s.scalars(select(GroceryItem)).all()
    aisle_order = {aisle: idx for idx, aisle in enumerate(AISLES)}
    return sorted(items, key=lambda x: (aisle_order.get(x.aisle, 99), x.name))

def update_grocery_item(s, item_id: int, name: str, amount: str, aisle: str) -> None:
    """Updates an item's name, amount, or moves it to a new aisle."""
    item = s.get(GroceryItem, item_id)
    if item:
        item.name = name.strip()
        item.amount = amount.strip()
        item.aisle = aisle
        s.commit()


def delete_grocery_item(s, item_id: int) -> None:
    """Deletes an item from the grocery list."""
    item = s.get(GroceryItem, item_id)
    if item:
        s.delete(item)
        s.commit()