"""Isolated temporary workspaces for offline engine regression scenarios."""
import pytest
from insight.bootstrap import Application, initialize_workspace


@pytest.fixture
def app(tmp_path):
    root = tmp_path / "workspace"
    initialize_workspace(root)
    application = Application(root)
    try:
        yield application
    finally:
        application.close()
