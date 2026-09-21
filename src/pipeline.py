from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Mapping, Sequence

import psycopg

from src.database import load_full_refresh
from src.models import DataValidationError, PreparedData, SCHEMA_NAME
from src.preparation import prepare_data


def print_report(
    prepared: PreparedData,
    loaded_counts: Mapping[str, int] | None = None,
) -> None:
    print("\nPipeline record report")
    print(
        f"{'dataset':28} {'source':>10} {'accepted':>10} {'failures':>10} "
        f"{'normalized':>11} {'deduped':>10} {'loaded':>10}"
    )
    for dataset, stats in prepared.stats.items():
        print(
            f"{dataset:28} {stats.source:10,d} {stats.accepted:10,d} "
            f"{stats.validation_failures:10,d} {stats.normalized:11,d} "
            f"{stats.deduplicated:10,d} {stats.loaded:10,d}"
        )

    print("\nValidation policy: fail on the first malformed, ambiguous, or conflicting record.")
    print("Safe normalization: surrounding whitespace is trimmed and counted by record.")
    print(
        "Sales without a source discount mapping: "
        f"{prepared.business_rule_counts['sales_without_discount_mapping']:,}"
    )
    print(
        "Missing product-city discount pairs: "
        f"{prepared.business_rule_counts['missing_product_city_discount_pairs']:,}"
    )
    print(f"Accepted sales quantity: {prepared.total_sales_units:,}")
    print("Prepared target records:")
    for table_name, record_count in prepared.expected_table_counts.items():
        loaded_suffix = ""
        if loaded_counts is not None:
            loaded_suffix = f"; loaded={loaded_counts[table_name]:,}"
        print(
            f"  {SCHEMA_NAME}.{table_name}: "
            f"prepared={record_count:,}{loaded_suffix}"
        )


def build_argument_parser() -> argparse.ArgumentParser:
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Validate and load the retail sales warehouse"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=repository_root / "data",
        help="Directory containing the three source CSV files",
    )
    parser.add_argument(
        "--schema-sql",
        type=Path,
        default=repository_root / "sql" / "schema.sql",
        help="Path to the idempotent PostgreSQL schema file",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection URL; defaults to DATABASE_URL",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate and transform the files without connecting to PostgreSQL",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if not args.validate_only and not args.database_url:
        parser.error(
            "--database-url or DATABASE_URL is required unless --validate-only is used"
        )

    try:
        with TemporaryDirectory(prefix="retail_sales_pipeline_") as temporary_directory:
            prepared = prepare_data(args.data_dir, Path(temporary_directory))
            if args.validate_only:
                print_report(prepared)
                return 0

            loaded_counts = load_full_refresh(
                prepared,
                args.database_url,
                args.schema_sql,
            )
            print_report(prepared, loaded_counts)
            print(
                "\nAtomic data refresh completed successfully. "
                "Schema DDL was applied in a separate transaction."
            )
            return 0
    except DataValidationError as exc:
        print(
            "Fail-fast validation stopped at the first failure; "
            f"the database was not changed: {exc}",
            file=sys.stderr,
        )
        return 1
    except (OSError, psycopg.Error, RuntimeError) as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
