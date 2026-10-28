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

    # Airflow 3's DagBag dropped the include_examples kwarg; scoping
    # dag_folder to our own dags/ directory achieves the same thing.
    dagbag = DagBag(dag_folder=str(DAGS_DIR))
    assert dagbag.import_errors == {}, dagbag.import_errors


def test_motor_claims_dag_loaded():
    from airflow.models import DagBag

    # Airflow 3's DagBag dropped the include_examples kwarg; scoping
    # dag_folder to our own dags/ directory achieves the same thing.
    #
    # Use dagbag.dags (populated purely by parsing) rather than
    # dagbag.get_dag(), which in Airflow 3 queries the metadata DB for
    # the DAG's current version -- that DB is never initialized here
    # (no `airflow db migrate` has run), so get_dag() fails with
    # "no such table: dag" even though parsing itself succeeded.
    dagbag = DagBag(dag_folder=str(DAGS_DIR))
    assert "motor_claims_ingest" in dagbag.dags
    dag = dagbag.dags["motor_claims_ingest"]
    task_ids = set(dag.task_ids)
    assert {"extract", "transform_task", "load_task", "dbt_build"} <= task_ids
