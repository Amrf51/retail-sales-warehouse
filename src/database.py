from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg import sql

from src.models import PreparedData, SCHEMA_NAME


COPY_COLUMNS = {
    "dim_product": [
        "product_id",
        "product_position",
        "promotion",
        "product_category",
        "seasonal",
        "brand",
        "url",
        "product_name",
        "description",
        "product_price",
        "currency",
        "terms",
        "section",
        "season",
        "material",
        "origin",
    ],
    "dim_city": ["city_id", "city_name"],
    "dim_date": [
        "date_id",
        "calendar_year",
        "calendar_quarter",
        "month_number",
        "month_name",
        "day_of_month",
        "day_of_week_number",
        "day_of_week_name",
        "is_weekend",
    ],
    "product_city_discount": ["product_id", "city_id", "discount_rate"],
    "fact_sales": [
        "source_record_number",
        "product_id",
        "city_id",
        "date_id",
        "sold_at",
        "pieces_sold",
    ],
}


def _qualified_table(table_name: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(
        sql.Identifier(SCHEMA_NAME),
        sql.Identifier(table_name),
    )


def _copy_csv(cursor: psycopg.Cursor, table_name: str, path: Path) -> None:
    statement = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT CSV)").format(
        _qualified_table(table_name),
        sql.SQL(", ").join(map(sql.Identifier, COPY_COLUMNS[table_name])),
    )
    with cursor.copy(statement) as copy:
        with path.open("r", encoding="utf-8", newline="") as source:
            while chunk := source.read(1024 * 1024):
                copy.write(chunk)


def _database_counts(cursor: psycopg.Cursor) -> dict[str, int]:
    counts = {}
    for table_name in COPY_COLUMNS:
        query = sql.SQL("SELECT COUNT(*) FROM {}").format(
            _qualified_table(table_name)
        )
        counts[table_name] = cursor.execute(query).fetchone()[0]
    return counts


def _verify_loaded_data(
    cursor: psycopg.Cursor,
    prepared: PreparedData,
) -> dict[str, int]:
    loaded_counts = _database_counts(cursor)
    if loaded_counts != prepared.expected_table_counts:
        raise RuntimeError(
            "Loaded row counts do not match prepared row counts: "
            f"expected={prepared.expected_table_counts}, loaded={loaded_counts}"
        )

    loaded_units_query = sql.SQL(
        "SELECT COALESCE(SUM(pieces_sold), 0) FROM {}"
    ).format(_qualified_table("fact_sales"))
    loaded_units = cursor.execute(loaded_units_query).fetchone()[0]
    if loaded_units != prepared.total_sales_units:
        raise RuntimeError(
            f"Loaded quantity does not reconcile: expected {prepared.total_sales_units}, "
            f"loaded {loaded_units}"
        )

    discount_join_query = sql.SQL(
        """
        SELECT
            COUNT(*),
            COALESCE(SUM(s.pieces_sold), 0),
            COUNT(*) FILTER (WHERE d.product_id IS NULL),
            COUNT(DISTINCT (s.product_id, s.city_id))
                FILTER (WHERE d.product_id IS NULL)
        FROM {} AS s
        LEFT JOIN {} AS d
          ON d.product_id = s.product_id
         AND d.city_id = s.city_id
        """
    ).format(
        _qualified_table("fact_sales"),
        _qualified_table("product_city_discount"),
    )
    (
        joined_rows,
        joined_units,
        sales_without_discount_mapping,
        missing_product_city_discount_pairs,
    ) = cursor.execute(discount_join_query).fetchone()
    if joined_rows != loaded_counts["fact_sales"] or joined_units != loaded_units:
        raise RuntimeError(
            "Left discount join changed the sales row count or total quantity: "
            f"sales=({loaded_counts['fact_sales']}, {loaded_units}), "
            f"joined=({joined_rows}, {joined_units})"
        )
    expected_unmatched = (
        prepared.business_rule_counts["sales_without_discount_mapping"],
        prepared.business_rule_counts["missing_product_city_discount_pairs"],
    )
    loaded_unmatched = (
        sales_without_discount_mapping,
        missing_product_city_discount_pairs,
    )
    if loaded_unmatched != expected_unmatched:
        raise RuntimeError(
            "Loaded unmatched discount counts do not match preparation: "
            f"expected={expected_unmatched}, loaded={loaded_unmatched}"
        )
    return loaded_counts


def _truncate_all_tables(cursor: psycopg.Cursor) -> None:
    tables = sql.SQL(", ").join(
        _qualified_table(table_name)
        for table_name in (
            "fact_sales",
            "product_city_discount",
            "dim_date",
            "dim_city",
            "dim_product",
        )
    )
    cursor.execute(
        sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY").format(tables)
    )


def _synchronize_city_identity(cursor: psycopg.Cursor) -> None:
    statement = sql.SQL(
        """
        SELECT setval(
            pg_get_serial_sequence({}, {}),
            (SELECT MAX(city_id) FROM {}),
            true
        )
        """
    ).format(
        sql.Literal(f"{SCHEMA_NAME}.dim_city"),
        sql.Literal("city_id"),
        _qualified_table("dim_city"),
    )
    cursor.execute(statement)


def load_full_refresh(
    prepared: PreparedData,
    database_url: str,
    schema_path: Path,
    *,
    fail_after_truncate: bool = False,
) -> dict[str, int]:
    """Apply idempotent DDL, then atomically replace the warehouse data."""
    schema_ddl = schema_path.read_text(encoding="utf-8")
    with psycopg.connect(database_url) as connection:
        # DDL is committed separately so a failed data refresh preserves the
        # previously committed warehouse contents.
        with connection.transaction():
            connection.execute(schema_ddl)

        # TRUNCATE, COPY, and reconciliation form the atomic data refresh.
        with connection.transaction():
            cursor = connection.cursor()
            _truncate_all_tables(cursor)
            if fail_after_truncate:
                raise RuntimeError("Simulated load failure after TRUNCATE")

            for table_name in COPY_COLUMNS:
                _copy_csv(cursor, table_name, prepared.files[table_name])

            _synchronize_city_identity(cursor)
            loaded_counts = _verify_loaded_data(cursor, prepared)

    prepared.stats["product_information.csv"].loaded = loaded_counts["dim_product"]
    prepared.stats["discount.csv"].loaded = loaded_counts[
        "product_city_discount"
    ]
    prepared.stats["products_sold.csv"].loaded = loaded_counts["fact_sales"]
    return loaded_counts
