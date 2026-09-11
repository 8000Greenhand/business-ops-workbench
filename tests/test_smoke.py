"""Smoke tests for the M0 project shell."""

from ops_workbench import __version__
from ops_workbench.app import APP_SUBTITLE, APP_TITLE, APP_VERSION_LABEL
from ops_workbench.utils.logging import get_logger


def test_m0_application_shell() -> None:
    """The package and minimal landing-page labels should be importable."""
    assert __version__ == "0.1.0"
    assert APP_TITLE == "Business Ops Workbench"
    assert APP_SUBTITLE == "经营诊断工作台"
    assert APP_VERSION_LABEL == "当前版本：M0 工程底座"
    assert get_logger("ops_workbench").name == "ops_workbench"
