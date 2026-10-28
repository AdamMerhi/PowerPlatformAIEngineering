"""DAG parse test. Airflow does not support running on Windows, so this
test is skipped there (and whenever apache-airflow isn't importable)
and runs for real on the Linux GitHub Actions runner.
"""
import sys
from pathlib import Path

import pytest

airflow = pytest.importorskip("airflow", reason="apache-airflow not installed")

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Airflow is not supported running on Windows; covered by CI on Linux instead.",
)

DAGS_DIR = Path(__file__).resolve().parent.parent / "dags"


def test_dagbag_has_no_import_errors():
    from airflow.models import DagBag

    dagbag = DagBag(dag_folder=str(DAGS_DIR), include_examples=False)
    assert dagbag.import_errors == {}, dagbag.import_errors


def test_motor_claims_dag_loaded():
    from airflow.models import DagBag

    dagbag = DagBag(dag_folder=str(DAGS_DIR), include_examples=False)
    dag = dagbag.get_dag("motor_claims_ingest")
    assert dag is not None
    task_ids = set(dag.task_ids)
    assert {"extract", "transform_task", "load_task", "dbt_build"} <= task_ids
