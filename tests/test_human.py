import statistics
from pathlib import Path

from ares3.core.engine import Engine
from ares3.plugins.physiology.human import HYPOXIA_TUC, sleep_stage, tloc_co2_s, tuc_hypoxia_s
from ares3.schemas.scenario import load_scenario

SCEN = Path(__file__).resolve().parents[1] / "scenarios" / "events"


def _run(name: str, ticks: int, npc: str, every: int = 1):
    eng = Engine(load_scenario(SCEN / f"{name}.yaml"))
    return [r.tick.npcs[npc] for i, r in enumerate(eng.run(ticks)) if i % every == 0]


def test_time_of_useful_consciousness_follows_the_faa_table():
    assert 1300 < tuc_hypoxia_s(69.6) < 1700  # 18,000 ft: 20-30 min
    pio2 = [p for p, _ in HYPOXIA_TUC]
    tucs = [tuc_hypoxia_s(p) for p in pio2[:-1]]
    assert tucs == sorted(tucs)  # lower PIO2 -> shorter TUC
    assert tuc_hypoxia_s(127.0) == float("inf") and tloc_co2_s(20.0) == float("inf")
    assert tloc_co2_s(76.0) < tloc_co2_s(53.0)


def test_sleep_hypnogram_shares():
    stages = [sleep_stage(m + 0.5) for m in range(450)]
    share = {s: stages.count(s) / len(stages) for s in (1, 2, 3, 5)}
    assert 0.10 <= share[3] <= 0.20 and 0.20 <= share[5] <= 0.26  # N3 10-20 %, REM 20-25 % [P16]
    assert stages[0] == 1 and stages[:30].count(3) == 0  # no N3 at onset


def test_decompression_is_survivable_unless_death_is_enabled():
    mortal = _run("eva_decompression_fatal", 4800, "med", every=60)
    safe = _run("eva_decompression", 4800, "med", every=60)
    assert mortal[-1].vitals["health_state"] == 4 and mortal[-1].vitals["gas_scale"] == 0.0
    assert mortal[-1].vitals["hr"] < 1.0
    assert max(n.vitals["health_state"] for n in safe) == 3  # unconscious, never dead
    assert safe[-1].vitals["gas_scale"] < 1.0  # an unconscious NPC stops working


def test_decompression_starts_from_the_briefs_vitals_and_death_is_zero():
    ticks = _run("eva_decompression_fatal", 4800, "med")
    first = ticks[4200]  # first tick of the rupture (10:10)
    assert 165 <= first.vitals["hr"] <= 173 and 80 <= first.vitals["spo2"] <= 89
    dead = ticks[-1].vitals
    assert dead["health_state"] == 4 and dead["hr"] == 0.0 and dead["spo2"] == 0.0 and dead["resp_rate"] == 0.0


def test_dead_rows_are_labelled_dead():
    eng = Engine(load_scenario(SCEN / "eva_decompression_fatal.yaml"))
    rows = [row for r in eng.run(4800) for row in r.rows if row["entity_id"] == "med" and row["metric"] == "hr"]
    assert rows[-1]["anomaly_type"] == "dead" and rows[-1]["is_anomaly"]


def test_af_spo2_wanders_between_91_and_94():
    sp = [n.vitals["spo2"] for n in _run("fibrillation", 4800, "eng")[4400:4800]]
    assert 90.5 <= min(sp) and max(sp) <= 94.5 and max(sp) - min(sp) > 0.8


def test_individual_parameters_use_sex_and_age():
    nom = _run("day_nominal", 2, "eng")[0].vitals, _run("day_nominal", 2, "med")[0].vitals
    assert nom[0]["hrv_rmssd"] > 0 and nom[1]["hrv_rmssd"] > 0
    men = _run("day_nominal", 2, "cmd")[0]
    assert men.sex == "M" and men.age_y and men.height_cm


def test_fever_and_dehydration_are_states_not_offsets():
    fever = _run("fever", 3600 * 5, "cmd", every=300)  # scenario starts at 07:00 -> last sample ~12:00
    healthy = _run("day_nominal", 3600 * 6 + 1, "cmd", every=3600 * 6)[-1]  # same clock time (12:00), no fever
    assert fever[-1].vitals["core_temp_c"] - healthy.vitals["core_temp_c"] > 1.0
    assert fever[-1].vitals["hr"] > healthy.vitals["hr"] + 8
    dehy = _run("dehydration", 3600 * 6, "bot", every=600)
    assert dehy[-1].vitals["dehydration_pct"] > 1.5


def test_atrial_fibrillation_makes_the_rr_series_irregular():
    ticks = _run("fibrillation", 4800, "eng")
    sinus = [n.vitals["rr_interval_ms"] for n in ticks[2000:3000]]
    af = [n.vitals["rr_interval_ms"] for n in ticks[4500:4800]]
    assert ticks[4700].vitals["rhythm"] == 1.0 and ticks[2500].vitals["rhythm"] == 0.0
    assert statistics.pstdev(af) / statistics.mean(af) > 0.08
    assert statistics.mean(af) < statistics.mean(sinus) * 0.7
