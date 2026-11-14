import json

import pandas as pd

from ares3.core.engine import Engine
from ares3.core.metabolism import DEFAULT_ACTIVITIES, rates_for
from ares3.export import DatasetWriter
from ares3.schemas.crew import ActivityBlock
from ares3.schemas.scenario import load_scenario
from conftest import SCENARIOS


def _rows(sc, ticks):
    return [r for res in Engine(sc).run(ticks) for r in res.rows]


def test_metabolism_reproduces_bvad_at_reference_mass():
    # BVAD Rev2 Tab 3-23/3-24 [S2], g/min of O2 and CO2 for the 82 kg reference man
    bvad = {"sleep": (0.37, 0.44), "nominal": (0.59, 0.69), "exercise_aerobic": (3.99, 5.22),
            "exercise_resistive": (1.43, 1.89), "recovery": (0.59, 0.69)}
    for name, (o2_g, co2_g) in bvad.items():
        r = rates_for(ActivityBlock(**{"from": 0, "to": 1, "activity": name, "module": "x"}), DEFAULT_ACTIVITIES, 82.0)
        assert abs(r.o2_mol_s * 60 * 31.998 - o2_g) / o2_g < 0.03, name
        assert abs(r.co2_mol_s * 60 * 44.01 - co2_g) / co2_g < 0.04, name


def test_same_seed_is_bit_identical_and_other_seed_differs(nominal):
    a, b = _rows(nominal, 120), _rows(nominal, 120)
    assert a == b
    other = nominal.model_copy(update={"file": nominal.file.model_copy(update={"seed": 99})})
    assert _rows(other, 120) != a


def test_nominal_hour_has_no_alarm_or_label(nominal):
    results = list(Engine(nominal).run(3600))
    assert not any(r.tick.alarms for r in results)
    assert not any(row["is_anomaly"] for r in results for row in r.rows)


def test_closed_system_conserves_every_species(nominal):
    closed = nominal.model_copy(update={"layout": nominal.layout.model_copy(update={"actuators": []})})
    eng = Engine(closed)
    before = {sp: eng.world.total_moles(sp) for sp in ("o2", "co2", "n2", "h2o")}
    # cool the habitat in the test only through UA: no source/sink besides the crew and condensation
    for _ in eng.run(3600):
        pass
    for sp in ("o2", "co2", "n2", "h2o"):
        booked = sum(v for k, v in eng.world.ledger.items() if k.endswith(f":{sp}"))
        assert abs(eng.world.total_moles(sp) - before[sp] - booked) < 1e-6 * before[sp], sp


def test_emergency_labels_follow_the_fault_window(emergency):
    seen, labelled = {}, set()
    for res in Engine(emergency).run(7300):  # the lab scrubber fails at 7200 s
        for row in res.rows:
            if row["is_anomaly"]:
                seen.setdefault(row["anomaly_type"], row["timestamp"])
                labelled.add(row["entity_id"])
    assert seen == {"scrubber_failure": 7200.0}
    # a failed lab scrubber labels the lab's sensors, never another module's
    assert "lab" in labelled and not labelled & {"hab", "greenhouse", "airlock"}


def test_environment_can_be_swapped_without_touching_the_layout(tmp_path):
    base = load_scenario(SCENARIOS / "nominal.yaml")
    from ares3.schemas.scenario import EnvironmentProfile, _read_yaml
    env = EnvironmentProfile.model_validate(_read_yaml(SCENARIOS / "environments" / "orbital_station.yaml"))
    orbit = base.model_copy(update={"environment": env})
    eng = Engine(orbit)
    results = list(eng.run(1800))
    assert abs(results[0].tick.modules["hab"].pressure_kpa - 101.3) < 0.01
    assert not any(r.tick.alarms for r in results)  # regulators follow the new setpoints


def test_export_chunks_and_manifest(nominal, tmp_path):
    sc = nominal.model_copy(update={"file": nominal.file.model_copy(
        update={"export": nominal.file.export.model_copy(update={"chunk_hours": 0.5})})})
    w = DatasetWriter(tmp_path, sc)
    for res in Engine(sc).run(3600):
        w.add(res)
    w.close()
    parts = sorted((tmp_path / "long").glob("part-*.parquet"))
    assert len(parts) == 2
    df = pd.concat(pd.read_parquet(p) for p in parts)
    assert list(df.columns)[:6] == ["tick", "timestamp", "sensor_id", "entity_id", "metric", "value"]
    assert len(df) == 3600 * len(sc.layout.sensors)
    assert (df["anomaly_type"] == "nominal").all()
    wide = pd.read_parquet(sorted((tmp_path / "wide").glob("part-*.parquet"))[0])
    assert "hab_ppCO2" in wide.columns and len(wide) == 1800
    assert json.loads((tmp_path / "manifest.json").read_text())["long_rows"] == len(df)


def test_sensor_sets_scale_without_touching_code(nominal):
    """120+ sensors from a handful of rules: the layout is data, the engine does not care how many."""
    from ares3.schemas.layout import LayoutConfig

    raw = nominal.layout.model_dump(exclude={"sensors"})
    raw["sensor_sets"] = [{
        "target_type": "module", "kind": "ares3.plugins.sensors.standard:ModuleSensor",
        "targets": ["all_modules"], "metrics": ["T", "RH", "ppCO2", "pO2", "P"], "id_template": "{target}_{metric}_a",
    }, {
        "target_type": "module", "kind": "ares3.plugins.sensors.standard:ModuleSensor",
        "targets": ["all_modules"], "metrics": ["T", "RH", "ppCO2", "pO2", "P"], "id_template": "{target}_{metric}_b",
    }, {
        "target_type": "npc", "kind": "ares3.plugins.sensors.standard:WearableSensor",
        "targets": ["all_npcs"], "metrics": ["hr", "spo2", "resp_rate", "hrv_rmssd", "skin_temp_c"],
    }]
    big = LayoutConfig.model_validate(raw).expand_sensor_sets([m.id for m in nominal.crew.members])
    assert len(big.sensors) == len(nominal.layout.modules) * 5 * 2 + 4 * 5
    sc = nominal.model_copy(update={"layout": big})
    res = list(Engine(sc).run(5))
    assert len(res[-1].observations) == len(big.sensors)
