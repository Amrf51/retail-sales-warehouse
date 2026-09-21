from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path


SCHEMA_NAME = "retail_sales"


class DataValidationError(ValueError):
    """Raised on the first source record that violates the data contract."""


@dataclass
class DatasetStats:
    source: int = 0
    accepted: int = 0
    validation_failures: int = 0
    normalized: int = 0
    deduplicated: int = 0
    loaded: int = 0


@dataclass
class PreparedData:
    output_dir: Path
    files: dict[str, Path]
    stats: dict[str, DatasetStats]
    expected_table_counts: dict[str, int]
    business_rule_counts: dict[str, int]
    total_sales_units: int


@dataclass
class PreparationContext:
    product_ids: set[int] = field(default_factory=set)
    discount_rates: dict[tuple[int, str], Decimal] = field(default_factory=dict)
    city_ids: dict[str, int] = field(default_factory=dict)
    sales_dates: set[date] = field(default_factory=set)
    missing_discount_sales: int = 0
    total_sales_units: int = 0
