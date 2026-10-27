from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    color: Mapped[str] = mapped_column(String(7))
    position: Mapped[int] = mapped_column(Integer, default=0)


meal_tags = Table(
    "meal_tags",
    Base.metadata,
    Column("meal_id", ForeignKey("meals.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    servings: Mapped[int | None] = mapped_column(Integer)
    total_minutes: Mapped[int | None] = mapped_column(Integer)
    steps: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tags: Mapped[list[Tag]] = relationship(secondary=meal_tags, order_by=Tag.name)
    ingredients: Mapped[list["Ingredient"]] = relationship(
        back_populates="meal", order_by="Ingredient.position", cascade="all, delete-orphan"
    )

    @property
    def step_list(self) -> list[str]:
        return [s.strip() for s in self.steps.splitlines() if s.strip()]


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_id: Mapped[int] = mapped_column(ForeignKey("meals.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    raw: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    amounts: Mapped[list] = mapped_column(JSONB, default=list)
    section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id", ondelete="SET NULL"))

    meal: Mapped[Meal] = relationship(back_populates="ingredients")
    section: Mapped[Section | None] = relationship()


class ItemSectionMap(Base):
    __tablename__ = "item_section_map"

    name_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))

    section: Mapped[Section] = relationship()


class PlanEntry(Base):
    __tablename__ = "plan_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    day: Mapped[date | None] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20), default="meal")  # meal | leftovers | eat_out
    meal_id: Mapped[int | None] = mapped_column(ForeignKey("meals.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_to_list: Mapped[bool] = mapped_column(Boolean, default=False)
    cooked_on: Mapped[date | None] = mapped_column(Date)

    meal: Mapped[Meal | None] = relationship()


class CookLog(Base):
    __tablename__ = "cook_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_id: Mapped[int] = mapped_column(ForeignKey("meals.id", ondelete="CASCADE"), index=True)
    cooked_on: Mapped[date] = mapped_column(Date)
    plan_entry_id: Mapped[int | None] = mapped_column(ForeignKey("plan_entries.id", ondelete="SET NULL"))

    meal: Mapped[Meal] = relationship()


class ListItem(Base):
    __tablename__ = "list_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200), index=True)
    amounts: Mapped[list] = mapped_column(JSONB, default=list)
    section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id", ondelete="SET NULL"))
    checked: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    section: Mapped[Section | None] = relationship()
    sources: Mapped[list["ListItemSource"]] = relationship(
        cascade="all, delete-orphan", order_by="ListItemSource.id"
    )


class ListItemSource(Base):
    __tablename__ = "list_item_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_item_id: Mapped[int] = mapped_column(ForeignKey("list_items.id", ondelete="CASCADE"), index=True)
    meal_id: Mapped[int | None] = mapped_column(ForeignKey("meals.id", ondelete="SET NULL"))
    meal_name: Mapped[str] = mapped_column(String(200))


class Staple(Base):
    __tablename__ = "staples"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    amounts: Mapped[list] = mapped_column(JSONB, default=list)
    section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id", ondelete="SET NULL"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    add_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    section: Mapped[Section | None] = relationship()
