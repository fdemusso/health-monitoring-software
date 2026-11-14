from ares3.core.engine import Engine
from ares3.plugins.physiology.toxicity import (
    CFKPerson,
    alveolar_ventilation_stpd_ml_min,
    cohb_equilibrium,
    cohb_step,
    effective_pio2,
)
from ares3.schemas.faults import FaultSpec
from ares3.schemas.scenario import load_scenario
from conftest import SCENARIOS

P, PIO2 = 101.06, 149.0
MAN = CFKPerson.from_anthropometrics("M", 75)
WOMAN = CFKPerson.from_anthropometrics("F", 61)
REST = alveolar_ventilation_stpd_ml_min(0.25, P)  # VCO2 at rest, L/min


def _eq(ppm, person=MAN, va=REST):
    return cohb_equilibrium(co_ppm=ppm, pressure_kpa=P, pio2_mmhg=PIO2, va_ml_min=va, person=person)


def test_cfk_matches_known_values():
    assert 0.2 < _eq(0) < 0.7  # endogenous CO only: ~0.5 % for a non-smoker
    assert 4.0 < _eq(35) < 6.5  # the classic ~5 % at 35 ppm
    assert 11.0 < _eq(100) < 16.0  # ~13-15 % at 100 ppm
    assert _eq(35) < _eq(50) < _eq(100) < _eq(400) < _eq(800) < 90  # monotonic, Haldane-like saturation


def test_cfk_kinetics_slow_rise_and_elimination_half_time_in_the_reported_range():
    x = _eq(0)
    for _ in range(3600):
        x = cohb_step(x, 1.0, co_ppm=100, pressure_kpa=P, pio2_mmhg=PIO2, va_ml_min=REST, person=MAN)
    assert 1.0 < x < 4.0  # one hour at 100 ppm: far from the 13 % equilibrium
    x, t = 20.0, 0
    while x > 10.0:
        x = cohb_step(x, 1.0, co_ppm=0, pressure_kpa=P, pio2_mmhg=PIO2, va_ml_min=REST, person=MAN)
        t += 1
    assert 2.0 < t / 3600 < 6.5  # WHO EHC 213: elimination half-time 2 to 6.5 h


def test_exercise_speeds_up_uptake_and_the_smaller_person_loads_faster():
    def after(va, person, minutes=120):
        x = _eq(0, person, va)
        for _ in range(minutes * 60):
            x = cohb_step(x, 1.0, co_ppm=300, pressure_kpa=P, pio2_mmhg=PIO2, va_ml_min=va, person=person)
        return x
    light = alveolar_ventilation_stpd_ml_min(0.65, P)
    assert after(light, MAN) > after(REST, MAN)
    assert after(REST, WOMAN) > after(REST, MAN)  # smaller blood volume


def test_effective_pio2_is_the_functional_equivalent_of_the_poisoning():
    assert effective_pio2(PIO2, 0.0) == PIO2
    assert effective_pio2(PIO2, 20.0) < effective_pio2(PIO2, 10.0) < PIO2
    assert effective_pio2(100.0, 20.0) < 100.0


# ---- in the simulation ---------------------------------------------------------------------------------
def _co_source(module="hab", mol_s=3.0e-3):  # ~850 ppm in the hub once it has spread to the connected modules
    return FaultSpec(id="co_leak", type="co_source", targets=[module], start_s=0, params={"mol_s": mol_s},
                     anomaly_type="co_release", priority=8)


def _exposed(station, minutes, crew_response=False, **kw):
    """The station with a CO source in the hub; by default nobody reacts, so the exposure runs its course."""
    sc = station.model_copy(update={"file": station.file.model_copy(update={"start_time_of_day_h": 7.5})})
    mon = sc.monitor
    if not crew_response:
        mon = mon.model_copy(update={"crew_response": None})
    elif kw:
        mon = mon.model_copy(update={"crew_response": mon.crew_response.model_copy(update=kw)})
    sc = sc.model_copy(update={"monitor": mon})
    eng = Engine(sc)
    for _ in eng.run(30):
        pass
    eng.inject(_co_source())
    results = list(eng.run(minutes * 60))
    return eng, results


def test_co_exposure_poisons_the_crew_the_pulse_oximeter_does_not_notice(station):
    _, res = _exposed(station, 120)
    first, last = res[0].tick.npcs["cmd"], res[-1].tick.npcs["cmd"]
    assert last.vitals["cohb_pct"] > 15.0 > first.vitals["cohb_pct"]
    assert last.vitals["hr"] > first.vitals["hr"] + 10  # functional hypoxia: tachycardia
    assert last.vitals["spo2"] > 96.0  # the pulse oximeter reads COHb as oxygenated haemoglobin
    assert res[-1].tick.modules["hab"].co_ppm > 100.0


def test_a_control_without_co_keeps_its_resting_cohb(station):
    sc = station.model_copy(update={"file": station.file.model_copy(update={"start_time_of_day_h": 7.5})})
    res = list(Engine(sc).run(3600))
    assert all(0.2 < r.tick.npcs[n].vitals["cohb_pct"] < 0.7 for n in ("cmd", "med") for r in res[::600])


def test_monitor_flags_the_crew_member_and_names_the_cause_from_the_sensors(station):
    _, res = _exposed(station, 150)
    log = [e for r in res for e in r.tick.monitor_events]
    confirmed = [e for e in log if e.kind == "emergency_confirmed" and e.message.startswith("medical")]
    assert confirmed and "co_poisoning" in confirmed[0].message
    em = next(e for r in res for e in r.tick.emergencies if e.kind == "medical" and e.state == "confirmed")
    assert em.subject in {"cmd", "bot", "med", "eng"} and em.cause == "co_poisoning" and em.module_id == "hab"
    # SpO2 alone would not have caught it: no hypoxia detector fired for the people poisoned only by CO
    assert not any("low_spo2" in e.detectors for r in res for e in r.tick.emergencies if e.cause == "co_poisoning")


def test_the_medic_goes_to_the_crew_member_the_monitor_flagged(station):
    _, res = _exposed(station, 150, crew_response=True, gather_on=[])
    assist = [e for r in res for e in r.tick.monitor_events if e.kind == "crew_assisting"]
    assert assist and "co_poisoning" in assist[0].message and assist[0].message.startswith("med goes to help cmd")
    # while assisting, the medic is next to the casualty, whatever her schedule says (she works in the lab at 07:30)
    helping = [r.tick.npcs["med"] for r in res if r.tick.npcs["med"].response_phase == "assist"]
    assert helping and helping[0].module_id == res[-1].tick.npcs["cmd"].module_id == "hab"


def test_toxicity_scenario_files_load():
    load_scenario(SCENARIOS / "events" / "debug_station.yaml")
