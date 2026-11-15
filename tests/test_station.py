"""The official ISS station (Mario's workbook): layout, engine additions (pressure-driven flow, orbit, structural leak, new
fault types), instruments, ECLSS actuators and the generated scenarios."""

import itertools
import subprocess
import sys

import pytest

from ares3.core import orbit
from ares3.core.engine import Engine
from ares3.plugins.actuators.eclss import Cdra
from ares3.schemas.environment import OrbitConfig
from ares3.schemas.faults import FaultSpec
from ares3.schemas.scenario import load_scenario
from conftest import ROOT, SCENARIOS

STATION = SCENARIOS / "station"


@pytest.fixture(scope="module")
def iss():
    return load_scenario(STATION / "nominal.yaml")


def _engine(iss):
    return Engine(iss)


# ---- the model as delivered -----------------------------------------------------------------------------------------------
def test_station_has_the_workbook_inventory(iss):
    mods = {m.id: m for m in iss.layout.modules}
    assert {"NOD1", "USL", "NOD2", "NOD3", "COL", "JPM", "CUP", "AL", "SM", "PRK", "CQ1", "CQ2", "CQ3", "CQ4"} <= set(mods)
    assert abs(mods["COL"].volume_m3 - 50.025) < 1e-3  # the only module whose free volume is measured [F15]
    assert abs(mods["USL"].volume_m3 - 68.9) < 1e-3
    assert len(iss.layout.hatches) == 14 and len(iss.layout.actuators) == 23 + 9
    # 62 environmental + 8 MCA + 26 telemetry (workbook) + the extras (lifeboat, eva, smoke/CO, wearables)
    ids = {s.id for s in iss.layout.sensors}
    assert {"usl_ppCO2_a", "mcaA_ppCO2", "cdraA_P_W", "oga_V_stack", "eps_SOC_bat", "cq4_ppCO2_a"} <= ids
    vehicles = [m.id for m in iss.layout.modules if m.return_vehicle]
    assert vehicles == ["lifeboat"]


def test_lifeboat_hatch_is_sealed_and_vents_cannot_close(iss):
    by = {h.key: h for h in iss.layout.hatches}
    assert by["H-NOD2-DRAGON"].open is False
    assert all(not by[f"V-NOD2-CQ{i}"].closable for i in range(1, 5))
    assert by["H-USL-NOD2"].imv == "IMV-USL-FWD"


def test_generated_files_match_the_workbook():
    pytest.importorskip("openpyxl")
    r = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "build_station.py"), "--check"], check=False, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_all_26_fault_scenarios_load_and_start():
    files = sorted((STATION / "events").glob("F-*.yaml"))
    assert len(files) == 26
    for f in files:
        sc = load_scenario(f)
        assert sc.faults.faults, f.name
        Engine(sc).step()  # builds every plugin and runs one tick


# ---- orbit (RC-2, RC-3) ----------------------------------------------------------------------------------------------------
def test_orbit_matches_the_iss_numbers():
    c = OrbitConfig()
    assert abs(orbit.period_s(c) / 60 - 92.82) < 0.05
    assert abs(orbit.critical_beta_deg(c) - 69.74) < 0.05
    assert abs(orbit.eclipse_fraction(c, 0.0) * orbit.period_s(c) / 60 - 35.97) < 0.05  # Mario's 36 min of shadow
    assert orbit.eclipse_fraction(c, 75.0) == 0.0  # beyond the critical beta: continuous sun


def test_battery_recharges_over_an_orbit():
    o = orbit.Orbit(OrbitConfig(soc0=1.0))
    lows, t = [], 0.0
    while t < 3 * o.period_s:
        st = o.step(t, 10.0, 9000.0)
        lows.append(st.soc)
        t += 10.0
    assert min(lows) > 0.6  # the eclipse takes ~24 % (Mario: 48 kWh of 200)
    last_orbit = lows[-round(o.period_s / 10):]
    assert max(last_orbit) > 0.97  # and the arrays bring it back before the next shadow


# ---- gas transport (RC-4) -----------------------------------------------------------------------------------------------------
def test_pressure_difference_equalises_through_an_open_hatch_and_conserves_gas(iss):
    eng = _engine(iss)
    w = eng.world
    w.modules["PRK"].n["n2"] *= 0.5  # half the nitrogen gone: a pressure hole in the vestibule
    total0 = {sp: w.total_moles(sp) for sp in ("o2", "co2", "n2", "h2o")}
    p0 = w.modules["PRK"].pressure_kpa
    for _ in range(30):
        w.step(1.0)
    assert w.modules["PRK"].pressure_kpa > p0 + 15.0  # refilled by the Zvezda side in seconds
    for sp, n in total0.items():
        assert abs(w.total_moles(sp) - n) < 1e-6 * n


def test_closed_hatch_only_leaks_through_the_seal(iss):
    eng = _engine(iss)
    w = eng.world
    assert w.set_hatch("SM", "PRK", False)
    w.modules["PRK"].n["n2"] *= 0.5
    dp0 = w.modules["SM"].pressure_kpa - w.modules["PRK"].pressure_kpa
    for _ in range(600):
        w.step(1.0)
    assert w.modules["SM"].pressure_kpa - w.modules["PRK"].pressure_kpa > 0.99 * dp0  # 1e-7 mol/(s kPa): nothing moves


def test_prk_leak_is_proportional_to_its_mass_flow(iss):
    sc = iss.model_copy(update={"faults": iss.faults.model_copy(update={"faults": [
        FaultSpec(id="leak", type="leak", targets=["PRK"], start_s=0, params={"kg_day": 1.0})]})})
    eng = _engine(sc)
    eng.world.set_hatch("SM", "PRK", False)
    p0 = eng.world.modules["PRK"].pressure_kpa
    for _ in range(3600):
        eng.step()
    # 1 kg/day of a 8.4 kg vestibule is 12 % a day: 0.5 kPa an hour at 101 kPa
    drop = p0 - eng.world.modules["PRK"].pressure_kpa
    assert 0.35 < drop < 0.65


# ---- faults and commands ------------------------------------------------------------------------------------------------------
def test_stuck_hatch_ignores_commands(iss):
    eng = _engine(iss)
    eng.inject(FaultSpec(id="stuck", type="hatch_stuck", targets=["H-SM-PRK"], start_s=0))
    eng._queued_hatches.append(("SM", "PRK", False))
    eng.step()
    assert eng.world.hatch_by_id["H-SM-PRK"].open
    eng.stop_event("stuck")
    eng.step()
    eng._queued_hatches.append(("SM", "PRK", False))
    eng.step()
    assert not eng.world.hatch_by_id["H-SM-PRK"].open


def test_degraded_imv_fan_moves_less_air_and_a_dead_one_none(iss):
    eng = _engine(iss)
    eng.step()
    base = eng.world.hatch_by_id["H-USL-NOD2"].exchange_m3_s
    assert abs(base - (0.1 + 140 * 4.71947e-4)) < 1e-6  # passive + the fan, Mario's 0.1661
    eng.inject(FaultSpec(id="foul", type="actuator_degrade", targets=["IMV-USL-FWD"], start_s=0, params={"fraction": 66 / 143}))
    eng.step()
    eng.step()
    now = eng.world.hatch_by_id["H-USL-NOD2"].exchange_m3_s
    assert abs(now - (0.1 + 140 * (66 / 143) * 4.71947e-4)) < 1e-6
    eng.inject(FaultSpec(id="dead", type="actuator_offline", targets=["IMV-USL-FWD"], start_s=0))
    eng.step()
    assert abs(eng.world.hatch_by_id["H-USL-NOD2"].exchange_m3_s - 0.1) < 1e-9


def test_stuck_open_pca_forces_nitrogen_in(iss):
    eng = _engine(iss)
    eng.inject(FaultSpec(id="pca", type="actuator_stuck", targets=["PCA"], start_s=0, params={"command": "on"}))
    n0 = eng.world.total_moles("n2")
    for _ in range(60):
        eng.step()
    assert eng.world.total_moles("n2") - n0 > 0.5  # 1e-2 mol/s for a minute, the valve ignoring the pressure


def test_label_marks_rows_of_a_module_whose_hatch_is_faulty(iss):
    eng = _engine(iss)
    eng.inject(FaultSpec(id="stuck", type="hatch_stuck", targets=["H-SM-PRK"], start_s=0, anomaly_type="portello_bloccato"))
    rows = [r for res in (eng.step() for _ in range(3)) for r in res.rows]
    assert any(r["anomaly_type"] == "portello_bloccato" and r["entity_id"] == "PRK" for r in rows)


# ---- ECLSS physics ---------------------------------------------------------------------------------------------------------------
def test_cdra_law_reproduces_the_workbook_equilibria():
    """R(pp) = R0 eta (pp/2)^0.8 against 4 people producing 1.052e-3 mol/s: 2.52 mmHg healthy, ~4.8 at 60 % capacity."""
    r0, eta, crew = 1.094e-3, 0.8, 4 * 1e3 / 44.009 / 86400

    def settle(cap):
        return 2.0 * (crew / (r0 * eta * cap)) ** (1 / 0.8)

    assert abs(settle(1.0) - 2.52) < 0.03
    assert abs(settle(0.6) - 4.77) < 0.1


def test_cdra_bed_swap_cuts_removal_for_a_minute(iss):
    eng = _engine(iss)
    cdra = next(a for a in eng.actuators if isinstance(a, Cdra) and a.id == "CDRA-A")
    p = cdra.params
    ctx = eng._ctx(eng._last_tick, {})

    def rate(t):
        c = ctx.__class__(tick=ctx.tick.model_copy(update={"t_sim_s": t}), env=ctx.env)
        return -cdra.step(1.0, c, None)[0].mol_s["co2"]

    assert rate(p.half_cycle_s + 10) == 0.0
    assert rate(p.half_cycle_s + 200) > 0.0


def test_standby_scrubber_is_off_until_woken(iss):
    eng = _engine(iss)
    eng.step()
    assert eng._act_telemetry["CDRA-B"]["P_W"] == 0.0
    assert eng._act_telemetry["CDRA-A"]["P_W"] == 1000.0


def test_nominal_station_holds_its_air_for_a_while(iss):
    eng = _engine(iss)
    for _ in range(2 * 3600):
        res = eng.step()
    t = res.tick
    for mid in ("USL", "NOD3", "CQ4", "SM"):
        m = t.modules[mid]
        assert 2.0 < m.ppco2_mmhg < 3.0, (mid, m.ppco2_mmhg)
        assert 100.0 < m.pressure_kpa < 102.7
        assert 18.0 < m.temperature_c < 27.0, (mid, m.temperature_c)
        assert 20.0 < m.rh_percent < 70.0, (mid, m.rh_percent)
    assert 20.7 < t.modules["NOD3"].gas.o2 < 21.7


# ---- instruments -----------------------------------------------------------------------------------------------------------------
def _obs(eng, sensor_id, n=1):
    out = []
    for _ in range(n):
        res = eng.step()
        out += [o for o in res.observations if o.sensor_id == sensor_id]
    return out


def test_units_of_the_same_model_carry_different_fixed_errors(iss):
    eng = _engine(iss)
    err = {"usl_ppCO2_a": [], "usl_ppCO2_b": []}
    for _ in range(200):
        for o in eng.step().observations:
            if o.sensor_id in err:
                err[o.sensor_id].append(o.value - o.value_true)
    mean = {k: sum(v) / len(v) for k, v in err.items()}
    assert abs(mean["usl_ppCO2_a"] - mean["usl_ppCO2_b"]) > 1e-3  # drawn once per unit: it does not average away
    assert all(abs(m) < 0.1 for m in mean.values())


def test_ndir_reads_pressure_as_co2(iss):
    from ares3.plugins.sensors.instruments import STD_PRESSURE_HPA

    eng = _engine(iss)
    s = next(x for x in eng.sensors if x.id == "usl_ppCO2_a")
    ctx = eng._ctx(eng._last_tick, {})
    mod = ctx.tick.modules["USL"]
    hi = ctx.tick.model_copy(update={"modules": {**ctx.tick.modules, "USL": mod.model_copy(
        update={"pressure_kpa": mod.pressure_kpa + 3.0})}})
    f_lo = s._cross_factor(ctx)
    f_hi = s._cross_factor(ctx.__class__(tick=hi, env=ctx.env))
    assert abs((f_hi - f_lo) - 0.0015 * 30) < 1e-3  # +3 kPa = 30 hPa = +4.5 % of the reading (the O2 term moves it by 0.05 %)
    assert STD_PRESSURE_HPA > 1000


def test_mca_samples_one_module_every_150_s_in_rotation(iss):
    eng = _engine(iss)
    obs = _obs(eng, "mcaA_ppCO2", 1500)
    assert [o.entity_id for o in obs[:8]] == ["NOD1", "USL", "NOD2", "NOD3", "COL", "JPM", "AL", "CUP"]
    assert [round(b.t_s - a.t_s) for a, b in itertools.pairwise(obs)] == [150] * (len(obs) - 1)


def test_actuator_telemetry_is_observed(iss):
    eng = _engine(iss)
    p = _obs(eng, "cdraA_P_W", 30)
    assert abs(sum(o.value for o in p) / len(p) - 1000.0) < 20.0
    assert all(o.entity_id == "CDRA-A" for o in p)


def test_condensate_follows_the_cold_loop(iss):
    eng = _engine(iss)
    for _ in range(600):
        eng.step()
    cond = eng._act_telemetry["CCAA-USL"]["cond_kg_h"]
    assert 0.0 < cond <= 1.2


def test_isolating_a_leaking_module_closes_its_hatches_but_not_the_lifeboat():
    sc = load_scenario(STATION / "events" / "F-FIS-PERDITA-RAPIDA.yaml")  # this event runs with the station monitor
    eng = Engine(sc)
    eng.inject(FaultSpec(id="hole", type="leak", targets=["COL"], start_s=0, params={"kpa_min": 4.0}, duration_s=1800))
    events = []
    for _ in range(240):
        events += eng.step().tick.monitor_events
    assert "emergency_confirmed" in {e.kind for e in events}
    assert not eng.world.hatch_by_id["H-NOD2-COL"].open  # COL isolated
    dragon = eng.world.hatch_by_id["H-NOD2-DRAGON"]
    assert not dragon.open and dragon.closable  # nobody opened or "closed" the vehicle's hatch
    assert all(eng.world.hatch_by_id[f"V-NOD2-CQ{i}"].open for i in range(1, 5))


# ---- the workbook's own balances (sheet 11_BILANCI) --------------------------------------------------------------------------
def test_time_constants_and_heating_rate_of_the_workbook(iss):
    mods = {m.id: m for m in iss.layout.modules}
    hatches = {h.key: h for h in iss.layout.hatches}
    fan = lambda hid: next(a for a in iss.layout.actuators if a.id == hatches[hid].imv).params["nominal_cfm"] * 4.71947e-4 
    lab_node2 = mods["USL"].volume_m3 / (hatches["H-USL-NOD2"].diffusion_coeff + fan("H-USL-NOD2")) / 60
    cabin = mods["CQ1"].volume_m3 / (hatches["V-NOD2-CQ1"].diffusion_coeff + fan("V-NOD2-CQ1")) / 60
    assert abs(lab_node2 - 6.91) < 0.05 and abs(cabin - 0.833) < 0.01
    assert abs(2000.0 / mods["USL"].thermal_mass_j_k * 3600 - 4.41) < 0.02  # a Lab without cooling: ~4.4 degC/h at 2 kW


def test_hatch_position_switch_follows_the_hatch(iss):
    eng = _engine(iss)
    eng.world.set_hatch("SM", "PRK", False)
    res = eng.step()
    pos = {o.sensor_id: o.value for o in res.observations}
    assert pos["pos_H-SM-PRK"] == 0.0 and pos["pos_H-NOD1-USL"] == 1.0


def test_tcs_holds_the_loop_until_it_loses_capacity(iss):
    from ares3.plugins.actuators.eclss import Tcs

    eng = _engine(iss)
    tcs = next(a for a in eng.actuators if isinstance(a, Tcs))
    tick = eng._last_tick.model_copy(update={"actuators": {"CCAA-USL": {"q_removed_w": 2000.0}}})
    ctx = eng._ctx(tick, {})
    for _ in range(3600):
        tcs.step(1.0, ctx, None)
    assert abs(tcs.telemetry()["T_loop"] - 4.4) < 1e-9  # 34 kW of 70: regulated
    lost = FaultSpec(id="loop", type="actuator_degrade", targets=["TCS"], start_s=0, params={"fraction": 0.4})
    ctx = eng._ctx(tick, {"TCS": (lost,)})
    for _ in range(3600):
        tcs.step(1.0, ctx, None)
    assert tcs.telemetry()["T_loop"] > 5.0  # 28 kW of capacity for 34 kW of heat: the cold loop warms


def test_oga_switches_on_below_the_band_after_its_start_up(iss):
    eng = _engine(iss)
    oga = next(a for a in eng.actuators if a.id == "OGA")
    tick = eng._last_tick
    low = tick.model_copy(update={"t_sim_s": 0.0})

    def run(t, reading):
        eng._readings["nod3_ppO2_a"] = eng._readings.get("nod3_ppO2_a") or type("O", (), {})()
        eng._readings["nod3_ppO2_a"].value = reading
        c = eng._ctx(low.model_copy(update={"t_sim_s": t}), {})
        return oga.step(1.0, c, None)

    assert "o2" not in run(0.0, 21.2)[0].mol_s  # inside the band: off
    assert "o2" not in run(1.0, 20.0)[0].mol_s  # below 20.7: starting up (standby power only)
    assert run(1000.0, 20.5)[0].mol_s["o2"] > 1.9e-3  # after the 900 s start-up: 1.953e-3 mol/s
    assert "o2" not in run(1001.0, 21.8)[0].mol_s  # above 21.7: off again
