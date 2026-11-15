"""Stage B plumbing: a ``diagnosis`` detector names the fault, the config table says what it opens, how fast, and in which colour."""

from ares3.core.engine import Engine
from ares3.schemas.monitor import ClassifierConfig, DetectorSpec, DiagnosisClass
from ares3.sdk import BaseDetector, Signal


class FakeDiagnoser(BaseDetector):
    """From t = 10 s it says ``degrado_cdra`` in hab; from t = 10 s also an unknown label (ignored: it is not in the table)."""

    def detect(self, ctx, observations):
        if ctx.tick.t_sim_s < 10:
            return []
        return [Signal(detector_id=self.id, emergency="anomaly", module_id="hab", severity="warning", cause="degrado_cdra",
                       evidence=("The CO2 scrubber removes less CO2", "hab_ppCO2: slope over 6 h (+4.0 sigma)")),
                Signal(detector_id=self.id, emergency="anomaly", module_id="lab", severity="warning", cause="not_in_the_table")]


def _engine(station):
    mon = station.monitor.model_copy(update={
        "detectors": [DetectorSpec(id="diag", kind="test_diagnosis:FakeDiagnoser", emergency="diagnosis")],
        "diagnosis": {"degrado_cdra": DiagnosisClass(emergency="equipment", severity="warning", confirm_s=20, clear_s=30)},
        "classifier": ClassifierConfig(confirm_s=5, clear_s=60, classes={"equipment:warning:degrado_cdra": "caution"}),
        "crew_response": None})
    return Engine(station.model_copy(update={"monitor": mon}))


def test_a_diagnosed_class_opens_the_emergency_the_table_says_with_its_own_timing(station):
    eng = _engine(station)
    seen, confirmed_at = {}, None
    for res in eng.run(60):
        for e in res.tick.emergencies:
            seen[e.id] = e
            if e.state == "confirmed" and confirmed_at is None:
                confirmed_at = res.tick.t_sim_s
    assert len(seen) == 1  # the label that is not in the table opens nothing
    em = next(iter(seen.values()))
    assert (em.kind, em.module_id, em.severity, em.cause, em.alert_class) == ("equipment", "hab", "warning", "degrado_cdra", "caution")
    assert em.evidence == ("The CO2 scrubber removes less CO2", "hab_ppCO2: slope over 6 h (+4.0 sigma)")
    assert 29 <= confirmed_at <= 31  # 20 s of the class, from the first signal at t = 10 s (not the classifier's 5 s)


def test_the_diagnosis_clears_with_its_own_clear_time(station):
    eng = _engine(station)
    cleared_at = None
    for res in eng.run(120):
        if res.tick.t_sim_s == 45:
            eng.monitor.detectors[0].detect = lambda ctx, obs: []  # the diagnoser stops seeing it
        if any(e.state == "cleared" for e in res.tick.emergencies) and cleared_at is None:
            cleared_at = res.tick.t_sim_s
    assert cleared_at is not None and 74 <= cleared_at <= 77  # last signal at 44 s + clear_s 30 s of the class
