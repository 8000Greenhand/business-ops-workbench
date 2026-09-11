"""Canonical schema for the daily business fact table."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, TypedDict

FACT_BUSINESS_DAILY_TABLE = "fact_business_daily"

ColumnKind = Literal["dimension", "metric"]
Aggregation = Literal["none", "sum"]


@dataclass(frozen=True, slots=True)
class ColumnMetadata:
    """Describe one canonical column without imposing a validation framework."""

    name: str
    python_type: type[object]
    nullable: bool
    kind: ColumnKind
    description: str
    aggregation: Aggregation = "none"


class CanonicalBusinessDaily(TypedDict):
    """Typed row representation for ``fact_business_daily``."""

    date: date
    business_line: str | None
    product: str | None
    channel: str | None
    region: str | None
    team: str | None
    salesperson: str | None
    impressions: int | None
    leads: int | None
    valid_leads: int | None
    contacted_leads: int | None
    followed_leads: int | None
    paid_users: int | None
    paid_orders: int | None
    gross_revenue: Decimal | None
    refund_users: int | None
    refund_orders: int | None
    refund_amount: Decimal | None


FACT_BUSINESS_DAILY_SCHEMA: tuple[ColumnMetadata, ...] = (
    ColumnMetadata("date", date, False, "dimension", "Business date"),
    ColumnMetadata("business_line", str, True, "dimension", "Business line"),
    ColumnMetadata("product", str, True, "dimension", "Product"),
    ColumnMetadata("channel", str, True, "dimension", "Acquisition or sales channel"),
    ColumnMetadata("region", str, True, "dimension", "Business region"),
    ColumnMetadata("team", str, True, "dimension", "Team"),
    ColumnMetadata("salesperson", str, True, "dimension", "Salesperson identifier"),
    ColumnMetadata("impressions", int, True, "metric", "Impressions", "sum"),
    ColumnMetadata("leads", int, True, "metric", "Leads", "sum"),
    ColumnMetadata("valid_leads", int, True, "metric", "Valid leads", "sum"),
    ColumnMetadata("contacted_leads", int, True, "metric", "Contacted leads", "sum"),
    ColumnMetadata("followed_leads", int, True, "metric", "Followed leads", "sum"),
    ColumnMetadata("paid_users", int, True, "metric", "Paid users", "sum"),
    ColumnMetadata("paid_orders", int, True, "metric", "Paid orders", "sum"),
    ColumnMetadata("gross_revenue", Decimal, True, "metric", "Gross revenue", "sum"),
    ColumnMetadata("refund_users", int, True, "metric", "Refunded users", "sum"),
    ColumnMetadata("refund_orders", int, True, "metric", "Refunded orders", "sum"),
    ColumnMetadata("refund_amount", Decimal, True, "metric", "Refund amount", "sum"),
)

CANONICAL_COLUMN_NAMES: tuple[str, ...] = tuple(
    column.name for column in FACT_BUSINESS_DAILY_SCHEMA
)

COLUMN_METADATA = MappingProxyType(
    {column.name: column for column in FACT_BUSINESS_DAILY_SCHEMA}
)

DATE_FIELD = "date"
DIMENSION_FIELDS: tuple[str, ...] = tuple(
    column.name
    for column in FACT_BUSINESS_DAILY_SCHEMA
    if column.python_type is str
)
INTEGER_FIELDS: tuple[str, ...] = tuple(
    column.name
    for column in FACT_BUSINESS_DAILY_SCHEMA
    if column.python_type is int
)
MONEY_FIELDS: tuple[str, ...] = tuple(
    column.name
    for column in FACT_BUSINESS_DAILY_SCHEMA
    if column.python_type is Decimal
)
