# Retail Sales Coding Challenge

Start with **[coding_challenge.ipynb](coding_challenge.ipynb)**. It contains the complete solution: CSV loading, data checks, cleaning, all three analytical tasks, tables, charts, and written answers. Saved outputs are included for immediate review.

## Run the standalone notebook

Use Python 3.12 or newer. From the repository folder:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
jupyter lab coding_challenge.ipynb
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.

Choose **Restart Kernel and Run All Cells**. The notebook reads the three supplied CSVs from `data/`. It also supports placing the CSVs directly beside the notebook; set `DATA_DIR` explicitly if your Jupyter working directory is elsewhere.

No PostgreSQL, Docker, environment file, or `src/` imports are required. To share the standalone solution, include the notebook, the three CSVs, and `requirements.txt` while preserving this layout:

```text
coding_challenge.ipynb
requirements.txt
data/
├── product_information.csv
├── products_sold.csv
└── discount.csv
```

## What the solution covers

- Removes repeated product-city discount mappings and rejects conflicting rates before joining.
- Checks required values, product references, quantities, prices, discounts, and UTC timestamps; verifies that joins preserve sales rows and units.
- **Task 1:** reports WOMAN/Winter units and assumed net sales value by city.
- **Task 1b:** applies each city's maximum supplied discount to the same sales with quantities fixed.
- **Task 2:** retains all tied best/worst products, compares nine attributes and monthly sales shares between best and worst sellers, with a compact catalogue reference and a supporting monthly line, and examines the relationship between sales-record counts and quantities.

The supplied extract contains 1,010,492 sales rows and 66,929,370 units. Removing 1,841 repeated discount rows prevents join inflation. Product prices and discounts have no historical validity dates, so monetary values are estimates, not recorded revenue. November is incomplete and December is absent.

Both analytical notebooks were executed from fresh kernels against the supplied CSVs and the populated PostgreSQL warehouse. All nine consistency checks pass in each notebook. Twelve analytical tables match, including the tied products, all nine attributes, supporting context, monthly totals, and sales-record diagnostic; all four charts render identically. The questions, analytical definitions, and written answers are aligned. The standalone notebook reads and cleans CSVs with pandas; the warehouse notebook uses pipeline-loaded PostgreSQL data and SQL sales aggregations. Source-cleaning reports remain specific to each workflow.

Task 2 also finds an exact numerical structure: every product has *n* sales records containing *n* units each, giving *n²* total units. This suggests constructed data, although the generation process is unknown; attribute differences should not be interpreted as proven drivers of retail demand.

## Optional warehouse extension

The PostgreSQL implementation is retained for reviewing schema design, validation, and transactional loading. It is independent of the standalone submission.

- [Data model and design decisions](docs/data_model.md)
- [Source profiling notebook](notebooks/profiling.ipynb)
- [SQL analytical notebook](notebooks/warehouse_analysis.ipynb)
- [Warehouse setup, pipeline behavior, and historical verification](docs/warehouse.md)

To run that extension from the repository root:

```bash
cp .env.example .env
docker compose up --build
```

Open [Jupyter at localhost:8888](http://localhost:8888), use the token from `.env`, and select `notebooks/warehouse_analysis.ipynb`. Compose starts PostgreSQL, loads the data, and then starts Jupyter. This setup is optional; the primary notebook runs directly from the CSVs.
