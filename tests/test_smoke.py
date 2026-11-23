"""The package and every planned module import, and the paths resolve to this repo."""

import importlib

import pytest

import yovahti
from yovahti import paths

MODULES = [
    "data", "world", "forecast", "energy", "twin", "plan", "baselines",
    "mcp_server", "agents", "netcrash", "trust", "arbiter", "watchdog", "report",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    mod = importlib.import_module(f"yovahti.{name}")
    assert mod.__doc__, f"yovahti.{name} needs a docstring saying what it is for"


def test_paths_point_at_repo():
    assert (paths.ROOT / "pyproject.toml").exists()
    assert paths.RAW.parent == paths.DATA


def test_version():
    assert yovahti.__version__
