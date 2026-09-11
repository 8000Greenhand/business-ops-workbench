"""Smoke tests for every Streamlit workbench shell script."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = ROOT / "src" / "ops_workbench" / "ui"


@pytest.mark.parametrize(
    "script",
    (
        UI_ROOT / "app.py",
        UI_ROOT / "pages" / "1_data_import.py",
        UI_ROOT / "pages" / "2_dataset_status.py",
        UI_ROOT / "pages" / "3_metrics.py",
        UI_ROOT / "pages" / "4_anomalies.py",
        UI_ROOT / "pages" / "5_diagnosis.py",
    ),
)
def test_streamlit_workbench_script_starts(script: Path) -> None:
    app = AppTest.from_file(script).run(timeout=15)
    assert not app.exception
