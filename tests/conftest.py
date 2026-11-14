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


@pytest.fixture
def station() -> Scenario:
    """The station (orbital_station profile, 101 kPa) with the monitoring system and no scheduled faults."""
    return load_scenario(SCENARIOS / "events" / "debug_station.yaml")
