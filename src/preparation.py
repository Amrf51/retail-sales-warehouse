from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from src.models import (
    DataValidationError,
    DatasetStats,
    PreparationContext,
    PreparedData,
)


PRODUCT_COLUMNS = [
    "Product ID",
    "Product Position",
    "Promotion",
    "Product Category",
    "Seasonal",
    "brand",
    "url",
    "name",
    "description",
    "price",
    "currency",
    "terms",
    "section",
    "season",
    "material",
    "origin",
]
DISCOUNT_COLUMNS = ["Product ID", "city", "discount"]
SALES_COLUMNS = ["Product ID", "pieces_sold", "city", "time"]


def extract_csv_records(
    path: Path,
    expected_columns: Sequence[str],
) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield one-based CSV data records after verifying the exact header."""
    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source, strict=True)
            if reader.fieldnames != list(expected_columns):
                raise DataValidationError(
                    f"{path.name}: expected header {list(expected_columns)!r}, "
                    f"found {reader.fieldnames!r}"
                )
            for source_record_number, record in enumerate(reader, start=1):
                if None in record:
                    raise DataValidationError(
                        f"{path.name} source record {source_record_number}: "
                        "contains more fields than the header"
                    )
                if any(value is None for value in record.values()):
                    raise DataValidationError(
                        f"{path.name} source record {source_record_number}: "
                        "contains fewer fields than the header"
                    )
                yield source_record_number, record
    except csv.Error as exc:
        raise DataValidationError(f"{path.name}: invalid CSV: {exc}") from exc
    except OSError as exc:
        raise DataValidationError(f"Cannot read {path}: {exc}") from exc


def _record_error(path: Path, source_record_number: int, message: str) -> DataValidationError:
    return DataValidationError(
        f"{path.name} source record {source_record_number}: {message}"
    )


def _normalize_whitespace(record: Mapping[str, str]) -> tuple[dict[str, str], bool]:
    normalized = {column: value.strip() for column, value in record.items()}
    changed = any(normalized[column] != value for column, value in record.items())
    return normalized, changed


def _required_text(
    record: Mapping[str, str],
    column: str,
    path: Path,
    source_record_number: int,
    max_length: int | None = None,
) -> str:
    value = record[column]
    if value == "":
        raise _record_error(path, source_record_number, f"{column!r} is required")
    if max_length is not None and len(value) > max_length:
        raise _record_error(
            path,
            source_record_number,
            f"{column!r} exceeds {max_length} characters",
        )
    return value


def _nullable_text(
    record: Mapping[str, str],
    column: str,
    path: Path,
    source_record_number: int,
    max_length: int | None = None,
) -> str | None:
    value = record[column]
    if value == "":
        return None
    if max_length is not None and len(value) > max_length:
        raise _record_error(
            path,
            source_record_number,
            f"{column!r} exceeds {max_length} characters",
        )
    return value


def _positive_integer(
    record: Mapping[str, str],
    column: str,
    path: Path,
    source_record_number: int,
) -> int:
    raw_value = record[column]
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise _record_error(
            path,
            source_record_number,
            f"{column!r} must be an integer, found {raw_value!r}",
        ) from exc
    if value <= 0:
        raise _record_error(
            path,
            source_record_number,
            f"{column!r} must be greater than zero",
        )
    if value > 2_147_483_647:
        raise _record_error(
            path,
            source_record_number,
            f"{column!r} exceeds PostgreSQL INTEGER range",
        )
    return value


def _decimal_value(
    record: Mapping[str, str],
    column: str,
    path: Path,
    source_record_number: int,
    *,
    minimum: Decimal,
    maximum: Decimal,
    max_scale: int,
) -> Decimal:
    raw_value = record[column]
    try:
        value = Decimal(raw_value)
    except InvalidOperation as exc:
        raise _record_error(
            path,
            source_record_number,
            f"{column!r} must be numeric, found {raw_value!r}",
        ) from exc
    if not value.is_finite():
        raise _record_error(path, source_record_number, f"{column!r} must be finite")
    if max(-value.as_tuple().exponent, 0) > max_scale:
        raise _record_error(
            path,
            source_record_number,
            f"{column!r} has more than {max_scale} decimal places",
        )
    if value < minimum or value > maximum:
        raise _record_error(
            path,
            source_record_number,
            f"{column!r} must be between {minimum} and {maximum}, found {value}",
        )
    return value


def _yes_no_boolean(
    record: Mapping[str, str],
    column: str,
    path: Path,
    source_record_number: int,
) -> bool:
    raw_value = record[column]
    if raw_value == "Yes":
        return True
    if raw_value == "No":
        return False
    raise _record_error(
        path,
        source_record_number,
        f"{column!r} must be 'Yes' or 'No', found {raw_value!r}",
    )


def _timestamp_utc(
    record: Mapping[str, str],
    column: str,
    path: Path,
    source_record_number: int,
) -> datetime:
    raw_value = record[column]
    try:
        return datetime.fromtimestamp(int(raw_value), tz=timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise _record_error(
            path,
            source_record_number,
            f"{column!r} must be a valid Unix timestamp in seconds, found {raw_value!r}",
        ) from exc


def _open_output(path: Path):
    return path.open("w", encoding="utf-8", newline="")


def validate_and_transform_products(
    source_path: Path,
    output_path: Path,
    stats: DatasetStats,
    context: PreparationContext,
) -> None:
    with _open_output(output_path) as target:
        writer = csv.writer(target, lineterminator="\n")
        for source_record_number, raw_record in extract_csv_records(
            source_path, PRODUCT_COLUMNS
        ):
            stats.source += 1
            record, normalized = _normalize_whitespace(raw_record)
            stats.normalized += int(normalized)
            try:
                product_id = _positive_integer(
                    record, "Product ID", source_path, source_record_number
                )
                if product_id in context.product_ids:
                    raise _record_error(
                        source_path,
                        source_record_number,
                        f"duplicate Product ID {product_id}",
                    )
                product_price = _decimal_value(
                    record,
                    "price",
                    source_path,
                    source_record_number,
                    minimum=Decimal("0.01"),
                    maximum=Decimal("99999999.99"),
                    max_scale=2,
                )
                transformed = [
                    product_id,
                    _required_text(
                        record,
                        "Product Position",
                        source_path,
                        source_record_number,
                        50,
                    ),
                    _yes_no_boolean(record, "Promotion", source_path, source_record_number),
                    _required_text(
                        record,
                        "Product Category",
                        source_path,
                        source_record_number,
                        50,
                    ),
                    _yes_no_boolean(record, "Seasonal", source_path, source_record_number),
                    _required_text(record, "brand", source_path, source_record_number, 100),
                    _required_text(record, "url", source_path, source_record_number),
                    _nullable_text(record, "name", source_path, source_record_number, 255),
                    _nullable_text(record, "description", source_path, source_record_number),
                    product_price,
                    _required_text(record, "currency", source_path, source_record_number, 3),
                    _required_text(record, "terms", source_path, source_record_number, 100),
                    _required_text(record, "section", source_path, source_record_number, 50),
                    _required_text(record, "season", source_path, source_record_number, 50),
                    _required_text(record, "material", source_path, source_record_number, 100),
                    _required_text(record, "origin", source_path, source_record_number, 100),
                ]
                if len(transformed[10]) != 3 or not transformed[10].isupper():
                    raise _record_error(
                        source_path,
                        source_record_number,
                        "'currency' must be a three-letter uppercase code",
                    )
            except DataValidationError:
                stats.validation_failures += 1
                raise
            context.product_ids.add(product_id)
            stats.accepted += 1
            writer.writerow(transformed)


def validate_and_collect_discounts(
    source_path: Path,
    stats: DatasetStats,
    context: PreparationContext,
) -> None:
    for source_record_number, raw_record in extract_csv_records(
        source_path, DISCOUNT_COLUMNS
    ):
        stats.source += 1
        record, normalized = _normalize_whitespace(raw_record)
        stats.normalized += int(normalized)
        try:
            product_id = _positive_integer(
                record, "Product ID", source_path, source_record_number
            )
            city = _required_text(record, "city", source_path, source_record_number, 100)
            discount_rate = _decimal_value(
                record,
                "discount",
                source_path,
                source_record_number,
                minimum=Decimal("0"),
                maximum=Decimal("1"),
                max_scale=4,
            )
            if product_id not in context.product_ids:
                raise _record_error(
                    source_path,
                    source_record_number,
                    f"unknown Product ID {product_id}",
                )
            key = (product_id, city)
            previous_rate = context.discount_rates.get(key)
            if previous_rate is not None:
                if previous_rate != discount_rate:
                    raise _record_error(
                        source_path,
                        source_record_number,
                        f"conflicting discounts for product {product_id} in {city}: "
                        f"{previous_rate} and {discount_rate}",
                    )
                stats.deduplicated += 1
            else:
                context.discount_rates[key] = discount_rate
                stats.accepted += 1
        except DataValidationError:
            stats.validation_failures += 1
            raise

    cities = sorted({city for _, city in context.discount_rates})
    context.city_ids = {city: city_id for city_id, city in enumerate(cities, start=1)}


def write_cities_and_discounts(
    city_path: Path,
    discount_path: Path,
    context: PreparationContext,
) -> None:
    with _open_output(city_path) as city_target:
        writer = csv.writer(city_target, lineterminator="\n")
        for city, city_id in context.city_ids.items():
            writer.writerow([city_id, city])

    with _open_output(discount_path) as discount_target:
        writer = csv.writer(discount_target, lineterminator="\n")
        for (product_id, city), discount_rate in sorted(context.discount_rates.items()):
            writer.writerow([product_id, context.city_ids[city], discount_rate])


def validate_and_transform_sales(
    source_path: Path,
    output_path: Path,
    stats: DatasetStats,
    context: PreparationContext,
) -> None:
    with _open_output(output_path) as target:
        writer = csv.writer(target, lineterminator="\n")
        for source_record_number, raw_record in extract_csv_records(
            source_path, SALES_COLUMNS
        ):
            stats.source += 1
            record, normalized = _normalize_whitespace(raw_record)
            stats.normalized += int(normalized)
            try:
                product_id = _positive_integer(
                    record, "Product ID", source_path, source_record_number
                )
                pieces_sold = _positive_integer(
                    record, "pieces_sold", source_path, source_record_number
                )
                city = _required_text(record, "city", source_path, source_record_number, 100)
                sold_at = _timestamp_utc(record, "time", source_path, source_record_number)
                if product_id not in context.product_ids:
                    raise _record_error(
                        source_path,
                        source_record_number,
                        f"unknown Product ID {product_id}",
                    )
                if (product_id, city) not in context.discount_rates:
                    context.missing_discount_sales += 1
                    raise _record_error(
                        source_path,
                        source_record_number,
                        f"missing discount for product {product_id} in {city}; "
                        "policy requires an explicit product-city discount",
                    )
            except DataValidationError:
                stats.validation_failures += 1
                raise

            sold_date = sold_at.date()
            context.sales_dates.add(sold_date)
            context.total_sales_units += pieces_sold
            stats.accepted += 1
            writer.writerow(
                [
                    source_record_number,
                    product_id,
                    context.city_ids[city],
                    sold_date.isoformat(),
                    sold_at.isoformat(),
                    pieces_sold,
                ]
            )


def write_date_dimension(output_path: Path, sales_dates: set[date]) -> int:
    if not sales_dates:
        raise DataValidationError("products_sold.csv contains no accepted records")

    first_date = min(sales_dates)
    last_date = max(sales_dates)
    row_count = 0
    with _open_output(output_path) as target:
        writer = csv.writer(target, lineterminator="\n")
        current_date = first_date
        while current_date <= last_date:
            weekday_number = current_date.isoweekday()
            writer.writerow(
                [
                    current_date.isoformat(),
                    current_date.year,
                    (current_date.month - 1) // 3 + 1,
                    current_date.month,
                    current_date.strftime("%B"),
                    current_date.day,
                    weekday_number,
                    current_date.strftime("%A"),
                    weekday_number >= 6,
                ]
            )
            row_count += 1
            current_date += timedelta(days=1)
    return row_count


def prepare_data(data_dir: Path, output_dir: Path) -> PreparedData:
    """Extract, validate, and transform every source before database mutation."""
    data_dir = data_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    source_paths = {
        "products": data_dir / "product_information.csv",
        "discounts": data_dir / "discount.csv",
        "sales": data_dir / "products_sold.csv",
    }
    for source_path in source_paths.values():
        if not source_path.is_file():
            raise DataValidationError(f"Required source file not found: {source_path}")

    files = {
        "dim_product": output_dir / "dim_product.csv",
        "dim_city": output_dir / "dim_city.csv",
        "dim_date": output_dir / "dim_date.csv",
        "product_city_discount": output_dir / "product_city_discount.csv",
        "fact_sales": output_dir / "fact_sales.csv",
    }
    stats = {
        "product_information.csv": DatasetStats(),
        "discount.csv": DatasetStats(),
        "products_sold.csv": DatasetStats(),
    }
    context = PreparationContext()

    validate_and_transform_products(
        source_paths["products"], files["dim_product"], stats["product_information.csv"], context
    )
    validate_and_collect_discounts(
        source_paths["discounts"], stats["discount.csv"], context
    )
    write_cities_and_discounts(
        files["dim_city"], files["product_city_discount"], context
    )
    validate_and_transform_sales(
        source_paths["sales"], files["fact_sales"], stats["products_sold.csv"], context
    )
    date_count = write_date_dimension(files["dim_date"], context.sales_dates)

    expected_table_counts = {
        "dim_product": stats["product_information.csv"].accepted,
        "dim_city": len(context.city_ids),
        "dim_date": date_count,
        "product_city_discount": len(context.discount_rates),
        "fact_sales": stats["products_sold.csv"].accepted,
    }
    for dataset, dataset_stats in stats.items():
        accounted_for = (
            dataset_stats.accepted
            + dataset_stats.validation_failures
            + dataset_stats.deduplicated
        )
        if dataset_stats.source != accounted_for:
            raise RuntimeError(
                f"Record accounting failed for {dataset}: source={dataset_stats.source}, "
                f"accepted+validation_failures+deduplicated={accounted_for}"
            )

    return PreparedData(
        output_dir=output_dir,
        files=files,
        stats=stats,
        expected_table_counts=expected_table_counts,
        business_rule_counts={
            "sales_missing_discount": context.missing_discount_sales,
        },
        total_sales_units=context.total_sales_units,
    )
