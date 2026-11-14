from pathlib import Path

import pytest

from ares3.schemas.scenario import Scenario, load_scenario

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "scenarios"


@pytest.fixture
def nominal() -> Scenario:
    return load_scenario(SCENARIOS / "nominal.yaml")


@pytest.fixture
def emergency() -> Scenario:
    return load_scenario(SCENARIOS / "emergency.yaml")
