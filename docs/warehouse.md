# Optional PostgreSQL Warehouse

This repository implements a reproducible PostgreSQL-backed data engineering challenge using three supplied CSV files. Python handles extraction, validation, transformation, and loading. PostgreSQL stores the dimensional model, while the final Jupyter notebook contains the analytical SQL, saved results, charts, and explanations.

The original task wording is also preserved in [`notebooks/warehouse_analysis.ipynb`](../notebooks/warehouse_analysis.ipynb). The complete warehouse contract is documented in [`docs/data_model.md`](../docs/data_model.md).

> The primary submission is the [standalone notebook](../coding_challenge.ipynb). This guide documents the optional warehouse implementation. Commands below run from the repository root. Verification results are historical, not checks rerun for the standalone conversion.

## Original project stages

| Stage | Status | Deliverable |
|---|---|---|
| 1. Inspect and profile | Complete | [`notebooks/profiling.ipynb`](../notebooks/profiling.ipynb) |
| 2. Model and business definitions | Complete | [`docs/data_model.md`](../docs/data_model.md) and [ERD on dbdiagram.io](https://dbdiagram.io/d/Retail_sales-6ab04e01943b561dd496d9cf) |
| 3. Schema and pipeline | Complete | [`sql/schema.sql`](../sql/schema.sql), the [`src`](../src) pipeline package, |
| 4. Containerized execution | Complete | [`Dockerfile`](../Dockerfile), [`compose.yaml`](../compose.yaml), pinned dependencies, and environment configuration |
| 5. Analytical notebook | Complete | Executed [`notebooks/warehouse_analysis.ipynb`](../notebooks/warehouse_analysis.ipynb) with SQL, tables, charts, and interpretation |
| 6. End-to-end verification | Complete | Unit tests, disposable PostgreSQL integration test, two full-data refreshes, and clean notebook execution |

## Architecture

```text
data/*.csv
    -> Python validation and transformation
    -> PostgreSQL COPY inside an atomic full refresh
    -> retail_sales dimensional model
    -> analytical SQL in notebooks/warehouse_analysis.ipynb
```

The implementation deliberately stays small: one schema file, one Python pipeline package, PostgreSQL, Docker Compose, and Jupyter. It does not add a migration framework, workflow orchestrator, or Makefile.

## Repository layout

```text
.
├── data/                       # Supplied CSV files, unchanged
├── docs/data_model.md          # Grain, keys, relationships, and assumptions
├── notebooks/profiling.ipynb   # Executed source-data profiling
├── sql/schema.sql              # Idempotent PostgreSQL schema
├── src/                        # Preparation, loading, and reporting code
├── notebooks/warehouse_analysis.ipynb      # Executed analytical answers
├── compose.yaml
└── Dockerfile
```

## Quick start with Docker

The only prerequisite is Docker Desktop or another Docker installation with Compose support.

Create the local environment file:

```bash
cp .env.example .env
```

The defaults are suitable for local development. If the password is changed, use URL-safe characters because Compose inserts it into the PostgreSQL connection URL.

Build the application image and start the complete workflow:

```bash
docker compose up --build
```

Compose starts the services in this order:

1. PostgreSQL starts and passes its `pg_isready` health check.
2. The one-shot `pipeline` service validates and loads the warehouse.
3. Jupyter starts only after the pipeline exits successfully.

The first pipeline run can take roughly half a minute on a typical laptop. Wait for `Atomic data refresh completed successfully` and the Jupyter startup message.

Open Jupyter at [http://localhost:8888](http://localhost:8888) and enter the `JUPYTER_TOKEN` from `.env`. The repository is mounted at `/app`, so notebook changes are saved to the host checkout.

PostgreSQL is exposed on `localhost:5432` by default. It is a database connection endpoint rather than a browser page. Use the database, user, password, and port from `.env` with a client such as DBeaver, DataGrip, pgAdmin, or `psql`. The warehouse tables are in the `retail_sales` schema.

List the loaded tables from inside the database container:

```bash
docker compose exec db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\\dt retail_sales.*"'
```

### Pipeline rerun

Rerun the full validation and atomic data refresh against the existing database:

```bash
docker compose run --rm pipeline
```

The refresh replaces the five challenge tables and does not append duplicate data. Rebuild the image first if Python, SQL, dependency, or source-data files changed:

```bash
docker compose build pipeline
docker compose run --rm pipeline
```

### Stop and restart

Stop the services while preserving PostgreSQL data:

```bash
docker compose down
```

Restart with:

```bash
docker compose up
```

### Destructive database reset

The following command permanently removes the project’s PostgreSQL volume and all loaded warehouse data:

```bash
docker compose down --volumes --remove-orphans
```

Run `docker compose up --build` afterward to create a fresh database and reload the source files.

Useful service logs:

```bash
docker compose logs pipeline
docker compose logs -f jupyter
docker compose logs -f db
```

## Source data

The supplied CSV files remain unchanged.

| File | Observed grain | Rows | Main role |
|---|---|---:|---|
| `data/product_information.csv` | One row per product | 20,252 | Product catalogue and supplied product price |
| `data/products_sold.csv` | One recorded sales observation | 1,010,492 | Quantities sold by product, city, and timestamp |
| `data/discount.csv` | Intended as one row per product and city | 185,962 | Undated product-city discount rates |

The profiling notebook uses a CSV-aware parser so quoted fields, including commas inside descriptions, are handled correctly.

## Profiling findings

### Product catalogue

- All 20,252 product IDs are complete and unique.
- There are no exact duplicate product rows.
- One product name and two descriptions are null. These are descriptive fields and do not prevent analysis.
- Prices are positive and range from 12.00 to 134.99.
- All product prices use USD.
- The supplied product price is not a transaction-level price captured separately for each sale.

### Sales

- The file contains 1,010,492 rows and 66,929,370 total units.
- Quantities are positive integers between 1 and 99.
- There are no exact duplicate rows.
- `(Product ID, city, time)` is unique in this extract, but the source provides no transaction ID or guarantee that this combination is a business key.
- Unix timestamps are interpreted as UTC and range from 2025-01-01 00:00:04 to 2025-11-29 23:59:10.
- There are no missing calendar days inside the observed range. November is incomplete and December is absent, which must be considered when comparing months.
- Every sales product exists in the catalogue, and every catalogue product appears in sales in this extract.

### Discounts

- The source contains 185,962 rows representing 184,121 unique product-city pairs.
- The 1,841 additional rows are exact duplicates.
- No product-city pair has conflicting discount rates in the supplied data.
- Discount rates range from 0.00 to 0.20.
- Discounts cover ten cities and have no effective date, expiry date, or discount identifier.
- Every observed sale has a matching product-city discount.

Joining sales directly to the raw discount file produces 1,020,777 rows, which is 10,285 more than the sales source. Removing exact discount duplicates restores a many-to-one join with 1,010,492 rows and preserves the total of 66,929,370 units.

## Business definitions

The original task uses the phrase “sales volume” while also asking that discounts be considered. Discounts cannot change the number of units sold, so the analysis will report two separate measures:

- **Unit sales volume:** `SUM(pieces_sold)`
- **Assumed net sales value:** `pieces_sold × product_price × (1 − discount_rate)`

The second measure is an analytical estimate. The source does not contain historical transaction prices or discounts effective at the sale timestamp, so it must not be described as recorded revenue.
All supplied products use USD, so current monetary outputs are USD. Converting or aggregating future mixed currencies is outside this challenge's scope.

### Task 1

Filter products where `section = 'WOMAN'` and `season = 'Winter'`, then group the qualifying sales by city. Report both units sold and assumed net sales value. Sales use a `LEFT JOIN` to source discount mappings and `COALESCE(discount_rate, 0)`, so an absent mapping has zero analytical effect without creating a warehouse row.

### Task 1b

For each city, find the maximum discount across all source mappings in that city. A city with no source mappings has a maximum rate of zero. Apply that city-level rate to the same qualifying sales used in Task 1, while keeping quantities and product prices unchanged. This is a comparison scenario, not a cleaning rule for duplicate or conflicting discounts.

### Task 2

Rank products by total units sold and retain all ties. Examine product attributes and monthly sales patterns. Start from the complete product dimension with a left join to sales so that catalogue products with no sales would remain eligible, even though the current extract contains no such products.

## Data model

The warehouse uses a small dimensional model. Its complete grain, key, relationship, and constraint contract is in [`docs/data_model.md`](../docs/data_model.md); the relationship diagram is also available in the [Retail Sales ERD on dbdiagram.io](https://dbdiagram.io/d/Retail_sales-6ab04e01943b561dd496d9cf).

| Table | Grain | Purpose |
|---|---|---|
| `dim_product` | One row per product | Product attributes, product price, and currency |
| `dim_city` | One row per city | Union of cities supplied by discounts and sales |
| `dim_date` | One row per calendar date | Consistent calendar attributes for time analysis |
| `fact_sales` | One row per accepted source sales row | Full UTC timestamp and observed quantity |
| `product_city_discount` | One row per supplied product-city pair | Source discount rate after exact deduplication; no synthetic rows |

### Key modeling decisions

- The source `Product ID` is a valid natural key for `dim_product`; an additional product surrogate key would add no value here.
- `fact_sales` preserves the source grain. `source_record_number` is the one-based CSV data-record number, excluding the header. It provides lineage without claiming to be a business transaction ID or physical file line number.
- The full sales timestamp is retained as `TIMESTAMPTZ`. The UTC calendar date also references `dim_date`.
- The sales fact stores observed quantities, not calculated revenue.
- Product price remains in `dim_product` because no transaction-level price history is available.
- Discount depends on both product and city, so it belongs in a separate associative table with a composite primary key.
- `fact_sales` has product, city, and date foreign keys, but no foreign key to `product_city_discount`: an absent product-city mapping is valid and means zero only at query time.
- `dim_city` starts with alphabetically sorted discount cities, then appends sales-only cities in deterministic first-seen order.
- Discount history is not modeled because the source provides no effective dates.
- Product attributes and prices are treated as one static snapshot because the source has no effective dates.
- Product attributes such as section, season, material, and promotion remain in `dim_product`. Separate dimensions for these small attributes would add joins without useful analytical behavior.

## Cleaning and validation rules

Validation is fail-fast: the pipeline stops at the first malformed, ambiguous, or conflicting source record. It therefore reports `validation_failures`, not a count that claims to include every possible rejected record in a failed file. All source files must pass before the database refresh begins.

The data-quality policy distinguishes three cases:

- **Safely correctable formatting:** trim surrounding whitespace and count how many source records were normalized. Internal whitespace is preserved.
- **Defined analytical default:** when a sale has no product-city row in `discount.csv`, accept the sale and use zero through `COALESCE` in analytical SQL. Do not create a discount row. Report affected sales and distinct missing pairs.
- **Malformed or invalid data:** fail on missing required values, invalid types or timestamps, orphan product references, quantities below one, product prices at or below zero, and discounts outside 0–1.
- **Ambiguous business values:** fail when one product-city pair has conflicting discount rates and require an explicit decision. Never choose the maximum silently as a cleaning rule.

Additional rules:

1. Preserve null product names and descriptions rather than inventing replacements.
2. Remove equivalent repeated product-city discount records, retaining one copy of the source rate. Retain source mappings that current sales do not use.
3. Treat a missing product-city discount mapping as zero in analysis while leaving it absent from `product_city_discount`. An explicit source zero and an absent mapping therefore calculate identically but remain distinguishable in lineage. This rule affects zero records in the supplied dataset.
4. Treat a zero product price as invalid. The challenge assumes every sold product has a strictly positive price; free products are outside the agreed business definition.
5. Preserve every accepted sales record and its full UTC timestamp. Do not impose sales uniqueness without a business identifier.
6. Verify after joining that both the sales record count and total quantity are unchanged.
7. Require the exact expected header-name set, reject missing, extra, or duplicate names, and accept any column order.

## Pipeline execution flow

```text
CSV files
    -> Python extraction and validation
    -> transformation and source-faithful exact discount deduplication
    -> atomic PostgreSQL data refresh
    -> analytical SQL in Jupyter
    -> saved tables, charts, and explanations
```

The pipeline validates and transforms every source into temporary load files before it changes database contents. Schema DDL is applied and committed separately. The subsequent `TRUNCATE`, PostgreSQL `COPY` operations, and reconciliation checks run inside one data transaction. A data-load or reconciliation failure rolls back the complete data refresh and preserves the previously committed warehouse contents. This is an atomic data refresh, not an atomic schema-and-data deployment.

The implementation is split by responsibility:

```text
src/
├── pipeline.py       # command-line arguments, reporting, and orchestration
├── preparation.py    # CSV extraction, normalization, validation, transformation
├── database.py       # COPY, transactions, refresh, and reconciliation
└── models.py         # shared dataclasses, schema name, and validation exception
```

Validate the complete source without connecting to PostgreSQL:

```bash
python -m src.pipeline --validate-only
```

Run the atomic data refresh against an existing PostgreSQL database:

```bash
export DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DATABASE"
python -m src.pipeline
```

Each successful run reports source, accepted, validation-failure, normalized, deduplicated, and loaded counts, plus `sales_without_discount_mapping` and `missing_product_city_discount_pairs`. Database reconciliation uses a left join, proves that sales rows and total units are preserved, and confirms the same unmatched counts without treating them as failures. On invalid input, fail-fast validation prints the first failure and confirms that the database was not changed. Successful reruns replace the challenge tables rather than appending records.

If using a checkout that includes the original tests, run the unit tests:

```bash
python -m unittest discover -s tests -v
```

The original PostgreSQL integration test requires an explicitly disposable database because it creates and removes the `retail_sales` schema:

```bash
export TEST_DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DISPOSABLE_TEST_DATABASE"
python -m unittest tests.test_pipeline.PostgreSQLRefreshIntegrationTest -v
```

The Compose services use `db:5432` internally. Host tools use `localhost` and the published `POSTGRES_PORT`, which defaults to `5432`.

## Saved analytical results

The optional warehouse notebook mirrors the standalone notebook’s questions, analytical definitions, result tables, charts, and written answers, using pipeline-loaded PostgreSQL data and SQL sales aggregations. Both were freshly executed after alignment: all nine consistency checks pass in each, twelve analytical tables match, and all four charts render identically. Source-cleaning reports remain specific to each workflow. Its main conclusions are:

- Task 1 qualifying sales total 11,461,620 units and an assumed net sales value of approximately $449.95 million across ten cities.
- In Task 1b, every city's maximum supplied discount is 20%. Applying that rate with quantities fixed produces an assumed net value of approximately $400.14 million, $49.82 million (11.07%) below the Task 1 estimate. This is an arithmetic scenario, not a demand or revenue forecast.
- Task 2 has broad ties: 202 products share the maximum of 9,801 units, and 201 products share the minimum of one unit. Selecting one product with `LIMIT 1` would be arbitrary.

See [`notebooks/warehouse_analysis.ipynb`](../notebooks/warehouse_analysis.ipynb) for the city tables, tie-aware product analysis, monthly patterns, charts, SQL, and limitations.

## Historical warehouse verification

The original warehouse implementation was checked against both the real source files and a disposable PostgreSQL 16 database:

- The original implementation recorded 13 passing unit tests; the test files are not present in this checkout.
- The PostgreSQL integration test passes, covering repeatable full refreshes, missing-discount behavior, and rollback after an injected failure.
- Source-only validation passes for all 1,010,492 sales records.
- Two consecutive full-data loads produce identical table counts and reconcile to 66,929,370 units, demonstrating idempotent reruns.
- The profiling notebook executes from a clean kernel with 11 code cells and no errors.
- The analytical notebook executes from a clean kernel with 13 code cells, no errors, and saved tables and charts.

The integration test is intentionally skipped by the normal unit-test command unless `TEST_DATABASE_URL` is set, protecting non-disposable databases from its schema cleanup.
