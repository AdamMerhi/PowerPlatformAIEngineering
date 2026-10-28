# INIT

Setup steps for getting started with this project.

## Prerequisites

- Git
- Power Platform CLI (`pac`) — `winget install Microsoft.PowerPlatformCLI`
- Access to a Power Platform developer environment
- (Optional) VS Code with the Power Platform Tools extension
- Python 3.13 (for the motor claims pipeline, dbt, and Airflow DAG parsing)
- A Snowflake account (trial is fine) with `snowflake/00_bootstrap.sql` run as `ACCOUNTADMIN`

## Setup

1. Clone the repository.
2. Authenticate: `pac auth create --environment <environment-url>`
3. Copy any required local settings into a `.env` file (git-ignored).
4. Verify connection: `pac org who`

### Motor claims pipeline (DAG C)

1. `python -m venv .venv && .venv\Scripts\activate` then `pip install -r requirements-dev.txt`.
2. Generate a Snowflake key pair and bootstrap the account (see `snowflake/00_bootstrap.sql` header), then run `snowflake/03_motor_claims_raw.sql`.
3. Fill in `.env` from `.env.example`; verify with `python scripts/check_snowflake.py`.
4. `pytest tests/` — unit tests, no Snowflake needed.
5. `python -m claims_pipeline run --dry-run` — extract + transform only, writes Parquet to `.cache/`.
6. `python -m claims_pipeline run` — full load into `RAW.MOTOR_CLAIMS_RAW`.
7. `dbt deps --project-dir dbt && dbt build --project-dir dbt --profiles-dir dbt`.

Airflow (`dags/motor_claims_ingest.py`) does not run natively on Windows; its logic lives in `claims_pipeline` so it's testable without a running Airflow instance. The daily production run is GitHub Actions (`.github/workflows/motor-claims-daily.yml`), not a hosted Airflow scheduler.

## Repository layout

| Path | Purpose |
|------|---------|
| `CLAUDE.md` | Instructions for Claude Code |
| `INIT.md` | Setup guide (this file) |
| `PLAN.md` | Roadmap and status |
| `claims_pipeline/` | DAG C pipeline logic: extract `dataCar` → transform → load to Snowflake |
| `dags/` | Airflow DAG definitions (thin wrappers over `claims_pipeline`) |
| `dbt/` | dbt project: staging/curated models and data-quality tests for DAG C |
| `snowflake/` | SQL run by hand to provision the Snowflake sandbox and tables |
| `scripts/` | PowerShell/Python setup and connectivity-check scripts |
| `tests/` | pytest unit tests for `claims_pipeline` and the DAG parse check |
| `.github/workflows/` | CI: lint/test on every push, daily ingest on a cron |
