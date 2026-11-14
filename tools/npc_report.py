"""Verification report for the bioengineer: what each NPC produces in a normal day and in every event scenario.

The report is written as HTML (output/npc_report/report.html, figures as PNG in img/) and converted to
output/npc_report/report.pdf with headless Chrome or Edge (any installed Chromium; no Python PDF library needed).

    uv sync --extra dev --extra report
    uv run python tools/npc_report.py              # runs every scenario (~10 min), writes report.html and report.pdf
    uv run python tools/npc_report.py --reuse      # re-plots from the cached runs

Scenarios: scenarios/nominal.yaml (baseline day), scenarios/events/*.yaml. Luca's rule functions are copied from
notebooks/luca/Critical_condition_monitor.ipynb and applied to the simulated EVA values.
"""

from __future__ import annotations

import argparse
import html
import math
import pickle
import shutil
import subprocess
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ares3.core.engine import Engine
from ares3.plugins.physiology.baseline import SPO2_VS_PIO2, spo2_from_pio2
from ares3.plugins.physiology.human import CO2_TLOC, HYPOXIA_TUC, STATE_NAMES
from ares3.schemas.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "npc_report"
IMG = OUT / "img"
MMHG = 7.50062
NPCS = ["cmd", "bot", "eng", "med"]  # = ASTRO_01, 02, 03, 04
ALIAS = {"cmd": "ASTRO_01", "bot": "ASTRO_02", "eng": "ASTRO_03", "med": "ASTRO_04"}
NAME = {n: f"{ALIAS[n]} ({n})" for n in NPCS}
COL = {"cmd": "#1b9e77", "bot": "#d95f02", "eng": "#7570b3", "med": "#e7298a"}
ACT_COL = {"sleep": "#4c72b0", "meal": "#ccb974", "nominal": "#8c8c8c", "work": "#8c8c8c", "rest": "#b0b0b0",
           "exercise_aerobic": "#d62728", "exercise_resistive": "#ff7f0e", "recovery": "#2ca02c"}
METRICS = {"hr": ("FC (bpm)", "hr"), "spo2": ("SpO2 (%)", "spo2"), "rr": ("Resp. (atti/min)", "resp_rate"),
           "hrv": ("HRV RMSSD (ms)", "hrv_rmssd"), "skin": ("T cutanea (C)", "skin_temp_c"),
           "core": ("T centrale (C)", "core_temp_c"), "state": ("Stato di salute (0-4)", "health_state"),
           "dehyd": ("Acqua persa (% massa)", "dehydration_pct"), "rrint": ("Intervallo RR (ms)", "rr_interval_ms"),
           "stage": ("Fase del sonno", "sleep_stage"), "nausea": ("Nausea (0-3)", "nausea"), "rhythm": ("Ritmo (1 = AF)", "rhythm")}
EVENTS = ["eva_nominal", "eva_decompression", "eva_decompression_fatal", "fibrillation", "scrubber_failure", "co2_release",
          "slow_leak", "dehydration", "stress", "fever", "motion_sickness"]
# Luca's brief: values he expects per astronaut (midpoint of his ranges)
LUCA = {"cmd": dict(hr=69.5, spo2=98.5, o2=21.0, co2=0.25, p=758.0), "bot": dict(hr=142.5, spo2=96.2, o2=20.8, co2=0.38, p=758.0),
        "eng": dict(hr=150.0, spo2=93.0, o2=20.8, co2=0.38, p=758.0), "med": dict(hr=132.5, spo2=94.0, o2=28.0, co2=0.15, p=350.0)}
LUCA_EMERG = dict(hr=172.0, spo2=88.0, o2=20.0, p=50.0, alt_m=7000)



# event -> (titolo, quando, cosa simula, da dove vengono i valori, cosa verificare)
EV_IT = {
    "eva_nominal": ("Uscita EVA senza problemi", "ASTRO_04, 10:00-10:30", "Passeggiata esterna di 30 minuti, supporto vitale della tuta attivo.",
                    "Atmosfera tuta: 350 mmHg, 42 % O2 (nostra assunzione, vedi pagina Ambiente); sforzo 7.2 MET (indicazione di Luca).",
                    "FC attorno a 125 bpm con 7.2 MET (la media NASA delle EVA e' 131-135) e SpO2 ~96 %: sono plausibili per una EVA? Nessun allarme atteso."),
    "eva_decompression": ("Decompressione esplosiva durante la EVA (morte disabilitata)", "ASTRO_04, evento alle 10:10",
                          "In un solo istante la pressione passa da 350 a 50 mmHg e il supporto vitale si spegne. L'astronauta perde coscienza e, con la morte disabilitata, resta incosciente (stato 3) ma la FC resta fissa a 172 bpm per l'adrenalina (opzione 'adrenergic_hr_bpm', solo in questo scenario).",
                          "Evento e pressioni dal brief di Luca; i vitali NON sono imposti (Luca: FC 172, SpO2 88): derivano dall'ossigeno inspirato. Perdita di coscienza dalla dose di ipossia (tempo di coscienza utile FAA [P21]); soglie ESTIMATE.",
                          "Quanti secondi servono per la perdita di coscienza (Luca: 9-15 s)? Dopo la perdita di coscienza la FC resta alta (150-175, adrenalina, come indicato da Luca); la versione con morte mostra invece il crollo finale. Quanto deve durare la FC alta prima di calare?"),
    "eva_decompression_fatal": ("Decompressione esplosiva durante la EVA (morte abilitata)", "ASTRO_04, evento alle 10:10",
                                "Stesso evento con la morte abilitata (opzione del modello): se la dose di ipossia supera 30 (circa 2 minuti di quasi vuoto) lo stato diventa 'morto'. FC, SpO2 e respirazione vanno a zero e l'NPC non scambia piu' gas.",
                                "Stesso evento; la dose di morte (30 volte il tempo di coscienza utile) e' ESTIMATE.",
                                "Un tempo alla morte di circa 2 minuti senza recompressione e' accettabile? Quale etichetta vuole nel dataset dopo la morte (serie che continua a zero o che si interrompe)?"),
    "fibrillation": ("Possibile fibrillazione atriale", "ASTRO_03, 11:10-11:25",
                     "Per 15 minuti la FC sale a 150 bpm, la SpO2 scende a 93 % e gli intervalli tra i battiti diventano irregolari (ritmo AF) mentre lavora in habitat.",
                     "FC 150 e SpO2 93 dal brief di Luca; irregolarita' (deviazione standard degli RR = 15 % della media, RMSSD ~85 ms, nell'intervallo 80-250 ms [P20]) e respirazione +3/min ESTIMATE.",
                     "Valori clinici confermati da Luca: FC 150 e SpO2 tra 91 e 94 % (l'ECG viene dal suo CSV, gli RR non servono)."),
    "scrubber_failure": ("Guasto del depuratore di CO2", "habitat, 13:00-23:00", "Il depuratore di CO2 dell'habitat si ferma per 10 ore; l'equipaggio continua a produrre CO2.",
                         "Evento fisico; effetto di CO2 su FC/respirazione: ESTIMATE (+1 bpm e +1.5 resp/min per mmHg sopra 2). Perdita di coscienza solo oltre 50 mmHg [P22].",
                         "La CO2 sale fino al limite NASA (3 mmHg) e fa scattare l'allarme: l'effetto sui vitali (piccolo) e' realistico?"),
    "co2_release": ("Rilascio improvviso di CO2", "habitat, 13:00-15:00", "Una sorgente di CO2 supera la capacita' del depuratore per 2 ore.",
                    "Evento fisico; stessa risposta dei vitali alla CO2 (ESTIMATE).",
                    "Come per il guasto del depuratore, con salita piu' rapida: confrontare tempi e soglie."),
    "slow_leak": ("Perdita lenta di pressione", "habitat, 13:00-19:00", "L'habitat perde lo 0.001 % di gas al secondo (~20 % in 6 ore); il regolatore compensa solo in parte.",
                  "Evento fisico; SpO2 dalla curva PIO2 [P1] (valida solo per ipossia marcata).",
                  "La pressione scende fino a toccare il limite NASA di ossigeno (122 mmHg)? I vitali dovrebbero reagire prima?"),
    "dehydration": ("Disidratazione progressiva", "ASTRO_02, 07:00-15:00",
                    "ASTRO_02 non beve e perde lo 0.5 % della massa corporea ogni ora per 8 ore (4 % in totale). FC, respirazione, HRV, temperatura cutanea e centrale seguono il deficit d'acqua; a fine evento la reidratazione chiude il deficit con costante di 2 ore.",
                    "3 bpm e +0.2 C di temperatura centrale per 1 % di massa persa [P17]; HRV, respirazione e pelle ESTIMATE.",
                    "0.5 %/h e' una perdita realistica? FC +12 bpm e temperatura centrale +0.8 C a fine evento sono ragionevoli? La reidratazione (2 h) e' troppo lenta?"),
    "stress": ("Stress acuto", "ASTRO_01, 10:00-12:00", "FC +10 bpm, respirazione +2/min, HRV ridotta del 40 % per 2 ore.",
               "Valori ESTIMATE (episodio imposto, nessuna fonte quantitativa).", "Valori e durata ragionevoli per uno stress acuto in missione?"),
    "fever": ("Febbre", "ASTRO_01, 08:00-14:00",
              "La temperatura centrale sale di 1.5 C per 6 ore; FC (+8.5 bpm per grado), respirazione (+2 per grado) e temperatura cutanea (+1 C) la seguono.",
              "8.5 bpm per grado C [P8]; respirazione, pelle e HRV ESTIMATE.",
              "La temperatura cutanea (misurata al polso) sale quanto la febbre? Come cambiano respirazione e HRV?"),
    "motion_sickness": ("Mal di spazio (nausea)", "ASTRO_02, 08:00-09:00",
                        "Un'ora di mal di spazio severo (primo giorno di missione, nausea 3 su 3): FC +9 bpm, respirazione +1.5/min, HRV -15 %, pelle piu' fredda.",
                        "Incidenza e gravita' dalle missioni Shuttle (67 % al primo volo: 30 % lieve, 24 % moderato, 13 % severo; 2-3 giorni) [P19]; effetto per livello ESTIMATE.",
                        "Intensita' e durata per livello sono ragionevoli? La nausea (0-3) e' una variabile utile nei dati?"),
}


# ---- atmosphere helpers -----------------------------------------------------------------------------
def isa_mmhg(h_m: float) -> float:
    if h_m <= 11000:
        return 760.0 * (1 - 2.25577e-5 * h_m) ** 5.25588
    return isa_mmhg(11000) * math.exp(-(h_m - 11000) / 6341.6)


def isa_altitude_m(p_mmhg: float) -> float:
    lo, hi = 0.0, 80000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if isa_mmhg(mid) > p_mmhg else (lo, mid)
    return (lo + hi) / 2


def pio2(p_mmhg: float, o2_pct: float) -> float:
    return max(0.0, (p_mmhg - 47.0) * o2_pct / 100.0)


def pio2_equiv_altitude_m(v: float) -> float:
    return isa_altitude_m(v / 0.2095 + 47.0) if v > 0 else float("inf")


# ---- Luca's rules (copied from Critical_condition_monitor.ipynb) ------------------------------------------
def monitor_analysis(alt: float) -> str:
    if alt < 1500:
        return "NOMINALE"
    if alt < 4500:
        return "PRE-ALLERTA"
    if alt < 6000:
        return "ATTENZIONE"
    if alt < 7500:
        return "PERICOLO"
    return "CRITICO ELEVATO"


def o2_minimum(feet: float) -> int:
    for limit, o2 in ((10000, 27), (20000, 35), (30000, 44), (40000, 78)):
        if feet <= limit:
            return o2
    return 100


def barotrauma(p0: float, p1: float, t_s: float) -> str:
    delta, rate = p0 - p1, (p0 - p1) / t_s if t_s > 0 else 0
    if t_s <= 0.5 and delta > 150:
        return "CRITICAL: DEPRESSURIZZAZIONE ESPLOSIVA"
    return "WARNING: DEPRESSURIZZAZIONE RAPIDA" if rate > 50 else "NOMINAL"


def monitora_atmosfera(num_astronauti, volume_modulo_m3, o2_perc_attuale, co2_perc_attuale, pressione_attuale_mmhg,
                      in_allenamento=False, eclss_attivo=True):
    """Copied from Critical_condition_monitor.ipynb (cell 'monitora_atmosfera_stazione_avanzato')."""
    volume_litri = volume_modulo_m3 * 1000
    consumo_o2_persona = 1.5 if in_allenamento else 0.3
    produzione_co2_persona = consumo_o2_persona * 0.85
    consumo_o2_ora = num_astronauti * consumo_o2_persona * 60
    produzione_co2_ora = num_astronauti * produzione_co2_persona * 60
    reintegro_o2_ora = 110.0 if eclss_attivo else 0.0
    rimozione_co2_ora = 95.0 if eclss_attivo else 0.0
    bilancio_o2 = reintegro_o2_ora - consumo_o2_ora
    bilancio_co2 = produzione_co2_ora - rimozione_co2_ora
    o2_1h = o2_perc_attuale + (bilancio_o2 / volume_litri) * 100
    co2_1h = max(0.04, co2_perc_attuale + (bilancio_co2 / volume_litri) * 100)
    ppo2 = pressione_attuale_mmhg * (o2_perc_attuale / 100)
    al = []
    if o2_perc_attuale < 19.5 or ppo2 < 148:
        al.append("CRITICAL ipossia ambientale")
    if o2_perc_attuale > 23.5:
        al.append("CRITICAL rischio incendio (O2 alto)")
    if co2_perc_attuale > 0.5:
        al.append("WARNING ipercapnia")
    if o2_1h < 19.5 or co2_1h > 0.5:
        al.append("ALERT PREVENTIVO sovraffollamento")
    return al, ppo2


def atmosphere_monitor_summary(r: dict, label: str) -> list:
    d = r["df"].iloc[::60]
    rows = []
    for mod, vol in (("hab", 60.0), ("eva", 12.0)):
        counts, ppo2s, n_min = {}, [], 0
        for _, x in d.iterrows():
            occ = [n for n in NPCS if x[f"{n}_mod"] == mod]
            if not occ:
                continue
            n_min += 1
            train = any(str(x[f"{n}_act"]).startswith("exercise") for n in occ)
            al, ppo2 = monitora_atmosfera(len(occ), vol, x[f"{mod}_o2pct"], x[f"{mod}_co2pct"], x[f"{mod}_P"], train, True)
            ppo2s.append(ppo2)
            for a in (al or ["NOMINAL"]):
                counts[a] = counts.get(a, 0) + 1
        if n_min:
            rows.append([label, "habitat" if mod == "hab" else "EVA", f"{n_min}", f"{min(ppo2s):.0f}-{max(ppo2s):.0f}",
                         "; ".join(f"{k}: {v} min" for k, v in counts.items())])
    return rows


# ---- simulation ---------------------------------------------------------------------------------------
def scenario_path(name: str) -> Path:
    return ROOT / "scenarios" / ("events/day_nominal.yaml" if name == "day" else "events/day_mars.yaml" if name == "day_mars"
                                 else f"events/{name}.yaml")


def run(name: str) -> dict:
    sc = load_scenario(scenario_path(name))
    eng = Engine(sc)
    ind = {n: dict(sex=eng.npcs[n].spec.sex, age=eng.npcs[n].spec.age_y, height=eng.npcs[n].spec.height_cm,
                   mass=eng.npcs[n].spec.body_mass_kg, hr_rest=eng.physiology[n].params.hr_rest, hr_max=eng.physiology[n].params.hr_max,
                   met_max=eng.physiology[n].params.met_max, hrv_rest=eng.physiology[n].params.hrv_rest,
                   sms=getattr(eng.physiology[n], "_sms_level", 0)) for n in NPCS}
    ticks = round(sc.file.duration_days * sc.environment.day_length_s / sc.file.dt_s)
    rec, alarms = [], []
    for res in eng.run(ticks):
        t = res.tick
        row = {"t": t.t_sim_s, "tod": t.time_of_day_h}
        for mid in ("hab", "eva"):
            m = t.modules[mid]
            row |= {f"{mid}_P": m.pressure_kpa * MMHG, f"{mid}_PIO2": m.pio2_mmhg, f"{mid}_ppCO2": m.ppco2_mmhg,
                    f"{mid}_T": m.temperature_c, f"{mid}_RH": m.rh_percent,
                    f"{mid}_o2pct": 100 * m.gas.o2 / m.pressure_kpa, f"{mid}_co2pct": 100 * m.gas.co2 / m.pressure_kpa}
        obs = {o.sensor_id: o.value for o in res.observations}
        anom = {r["entity_id"]: r["anomaly_type"] for r in res.rows if r["is_anomaly"] and r["metric"] == "hr"}
        for n, s in t.npcs.items():
            for k, (_, v) in METRICS.items():
                row[f"{n}_{k}"] = s.vitals[v]
            row[f"{n}_hr_s"], row[f"{n}_spo2_s"] = obs[f"{n}_hr"], obs[f"{n}_spo2"]
            row[f"{n}_act"], row[f"{n}_mod"] = s.activity, s.module_id
            row[f"{n}_anom"] = anom.get(n, "nominal")
        rec.append(row)
        alarms += [{"t": t.t_sim_s, "code": a.code, "module": a.module_id, "value": a.value} for a in t.alarms]
    faults = [dict(id=f.id, type=f.type, targets=f.targets, start=f.start_s, end=f.start_s + (f.duration_s or 1e12),
                   label=f.label, params=f.params) for f in sc.faults.faults]
    return {"df": pd.DataFrame(rec), "alarms": pd.DataFrame(alarms), "faults": faults, "start_tod": sc.file.start_time_of_day_h,
            "name": sc.file.name, "ind": ind}


def load_all(reuse: bool) -> dict[str, dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    out = {}
    for name in ["day", "day_mars", *EVENTS]:
        cache = OUT / f"cache_{name}.pkl"
        if reuse and cache.exists():
            out[name] = pickle.loads(cache.read_bytes())
        else:
            print("running", name, flush=True)
            out[name] = run(name)
            cache.write_bytes(pickle.dumps(out[name]))
        df = out[name]["df"]
        df.iloc[::60].to_csv(OUT / f"data_{name}_1min.csv", index=False)
    return out


# ---- PDF helpers --------------------------------------------------------------------------------------
def hours(run_: dict) -> np.ndarray:
    return run_["start_tod"] + run_["df"]["t"].values / 3600.0


CSS = """
@page { size: A4 landscape; margin: 11mm 12mm 13mm 12mm; @bottom-right { content: counter(page); font: 8pt Segoe UI, Arial, sans-serif; color: #666; } }
* { box-sizing: border-box; }
body { font: 9.6pt/1.42 "Segoe UI", Arial, sans-serif; color: #1c1c1c; margin: 0; }
section { break-after: page; }
section:last-of-type { break-after: auto; }
h1 { font-size: 16pt; margin: 0 0 7px; padding-bottom: 4px; border-bottom: 2px solid #34495e; color: #1d2b3a; }
h2 { font-size: 11.2pt; margin: 11px 0 3px; color: #1d2b3a; break-after: avoid; }
p { margin: 0 0 6px; text-align: left; }
p.explain { background: #eef3f8; border-left: 4px solid #4a76a8; padding: 5px 9px; margin: 4px 0 6px; font-size: 9pt; }
p.note { font-size: 8.6pt; color: #333; margin-top: 7px; }
p.check { background: #fff6e0; border-left: 4px solid #e0a020; padding: 5px 9px; margin-top: 7px; font-weight: 600; }
img { display: block; max-width: 100%; max-height: 118mm; margin: 4px auto; }
img.tall { max-height: 128mm; }
table { border-collapse: collapse; width: 100%; font-size: 8.3pt; table-layout: fixed; margin: 4px 0; }
th, td { border: 1px solid #b8c0c8; padding: 3px 5px; vertical-align: top; overflow-wrap: anywhere; }
th { background: #dde3ea; text-align: left; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
.small table { font-size: 7.6pt; }
.ev img { max-height: 80mm; }
.ev p { margin-bottom: 4px; }
.ev table { margin: 2px 0; }
.cols { display: flex; gap: 14px; align-items: flex-start; }
.cols > div { flex: 1; }
"""


def esc(x) -> str:
    return html.escape(str(x))


class Doc:
    """Sections of the HTML report. Figures are saved as PNG next to the HTML and referenced by relative path."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.n_img = 0
        shutil.rmtree(IMG, ignore_errors=True)
        IMG.mkdir(parents=True, exist_ok=True)

    def add(self, title: str, body: str, cls: str = "") -> None:
        self.parts.append(f'<section class="{cls}"><h1>{esc(title)}</h1>{body}</section>')

    def fig(self, fig, title: str, explain: str, after: str = "", cls: str = "", tall: bool = False, intro: str = "") -> None:
        self.n_img += 1
        name = f"fig{self.n_img:02d}.png"
        fig.savefig(IMG / name, dpi=150, bbox_inches="tight")
        plt.close(fig)
        self.add(title, f'{intro}<p class="explain">{esc(explain)}</p><img class="{"tall" if tall else ""}" src="img/{name}">{after}', cls)

    def write(self) -> Path:
        out = OUT / "report.html"
        out.write_text(f'<!doctype html><html lang="it"><head><meta charset="utf-8"><title>ARES 3 - verifica degli NPC</title>'
                       f"<style>{CSS}</style></head><body>{''.join(self.parts)}</body></html>", encoding="utf8")
        return out


def blocks_html(blocks: list[str]) -> str:
    out = []
    for b in blocks:
        out.append(f"<h2>{esc(b.lstrip('# ').strip())}</h2>" if b.startswith("##") else f"<p>{esc(b)}</p>")
    return "".join(out)


def table_html(df: pd.DataFrame, col_w=None) -> str:
    w = col_w or [1.0 / len(df.columns)] * len(df.columns)
    cols = "".join(f'<col style="width:{100 * x:.1f}%">' for x in w)
    head = "".join(f"<th>{esc(c)}</th>" for c in df.columns)
    body = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>" for row in df.values)
    return f"<table><colgroup>{cols}</colgroup><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def text_page(doc: Doc, title: str, blocks: list[str]) -> None:
    doc.add(title, blocks_html(blocks))


def table_page(doc: Doc, title: str, df: pd.DataFrame, note: str = "", col_w=None, intro: str = "", cls: str = "") -> None:
    doc.add(title, (f'<p class="explain">{esc(intro)}</p>' if intro else "") + table_html(df, col_w)
            + (f'<p class="note">{esc(note)}</p>' if note else ""), cls)


def to_pdf(src: Path, dst: Path) -> bool:
    """Print the HTML with a headless Chromium browser (Chrome or Edge)."""
    candidates = [shutil.which(x) for x in ("chrome", "google-chrome", "chromium", "msedge")] + [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
    browser = next((c for c in candidates if c and Path(c).exists()), None)
    if browser is None:
        print("no Chrome/Edge found: open report.html and print it to PDF")
        return False
    with tempfile.TemporaryDirectory() as prof:
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={prof}",
                        f"--print-to-pdf={dst}", src.as_uri()], check=True, timeout=300, capture_output=True)
    return dst.exists()


def activity_strip(ax, run_: dict, npc: str) -> None:
    df, h = run_["df"], hours(run_)
    act = df[f"{npc}_act"].values
    start = 0
    for i in range(1, len(act) + 1):
        if i == len(act) or act[i] != act[start]:
            ax.axvspan(h[start], h[i - 1] + 1 / 3600, color=ACT_COL.get(act[start], "#aaa"), lw=0)
            start = i
    ax.set_yticks([])
    ax.set_ylim(0, 1)


def shade_faults(ax, run_: dict, npc: str | None = None) -> None:
    for f in run_["faults"]:
        ax.axvspan(run_["start_tod"] + f["start"] / 3600, run_["start_tod"] + min(f["end"], run_["df"]["t"].iloc[-1]) / 3600 + 1 / 3600,
                   color="#d62728", alpha=0.10, lw=0)


# ---- findings (computed) --------------------------------------------------------------------------------
def stats_by_activity(r: dict) -> pd.DataFrame:
    rows = []
    for n in NPCS:
        d = r["df"]
        for act, g in d.groupby(f"{n}_act"):
            if len(g) < 120:
                continue
            rows.append(dict(npc=n, act=act, minutes=len(g) / 60, **{k: g[f"{n}_{k}"].mean() for k in METRICS}))
    return pd.DataFrame(rows)


def event_table(r: dict, npc: str, mets: list[str], ev: str) -> pd.DataFrame:
    """Mean 30 min before the event, min/max during, mean 30 min after (whole run for events without a fault window)."""
    d = r["df"]
    f0 = min(f["start"] for f in r["faults"]) if r["faults"] else None
    f1 = max(min(f["end"], d["t"].iloc[-1]) for f in r["faults"]) if r["faults"] else None
    rows = []
    for k in mets:
        s = d[f"{npc}_{k}"]
        if f0 is None:
            sel = d[d[f"{npc}_mod"] == "eva"] if ev == "eva_nominal" else d
            rows.append([METRICS[k][0], f"{sel[f'{npc}_{k}'].mean():.1f}", f"{sel[f'{npc}_{k}'].min():.1f}", f"{sel[f'{npc}_{k}'].max():.1f}", "-"])
            continue
        pre = s[(d.t >= f0 - 1800) & (d.t < f0)].mean()
        win = s[(d.t >= f0) & (d.t <= f1)]
        post = s[(d.t > f1) & (d.t <= f1 + 1800)].mean()
        rows.append([METRICS[k][0], f"{pre:.1f}", f"{win.min():.1f}", f"{win.max():.1f}", f"{post:.1f}" if not np.isnan(post) else "-"])
    head = (["Grandezza", "media 30 min prima", "minimo nell'evento", "massimo nell'evento", "media 30 min dopo"] if f0 is not None
            else ["Grandezza", "media (nella EVA)", "minimo", "massimo", "-"])
    return pd.DataFrame(rows, columns=head)


def event_notes(r: dict, npc: str) -> str:
    al = r["alarms"]
    if len(al):
        g = al.groupby(["code", "module"]).agg(first=("t", "min"), last=("t", "max"), n=("t", "count")).reset_index()
        txt = "Allarmi NASA: " + "; ".join(f"{x.code}/{x.module} {(r['start_tod'] + x['first'] / 3600) % 24:.2f}h-{(r['start_tod'] + x['last'] / 3600) % 24:.2f}h ({x.n} s)"
                                           for _, x in g.iterrows())
    else:
        txt = "Allarmi NASA: nessuno."
    labs = r["df"][f"{npc}_anom"].value_counts()
    txt += f" Etichette scritte nel dataset per {npc} (fault attivo): " + ", ".join(f"{k} {v} s" for k, v in labs.items()) + "."
    st = r["df"][f"{npc}_state"]
    if st.max() > 0:
        txt += " Stato di salute massimo raggiunto: " + STATE_NAMES[int(st.max())] + "."
    return f'<p class="note">{esc(txt)}</p>'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true")
    args = ap.parse_args()
    R = load_all(args.reuse)
    day, daym = R["day"], R["day_mars"]
    ecg = pd.read_csv(ROOT / "notebooks" / "luca" / "ecg_dataset_megatron.csv", header=None).values
    rng = np.random.default_rng(42)

    def ecg_row(label):
        return int(rng.choice(np.flatnonzero(ecg[:, -1] == label)))

    # numbers used by the findings -------------------------------------------------------------------------
    dd = day["df"]
    sa = stats_by_activity(day)

    def act_mean(n, act, k):
        v = sa[(sa.npc == n) & (sa.act == act)][k]
        return float(v.iloc[0]) if len(v) else float("nan")

    cmd_work = act_mean("cmd", "work", "hr")
    bot_ex = act_mean("bot", "exercise_aerobic", "hr")
    cmd_sleep = act_mean("cmd", "sleep", "hr")
    spo2_station = act_mean("cmd", "work", "spo2")
    spo2_mars = float(stats_by_activity(daym).query("npc=='cmd' and act=='work'").spo2.iloc[0])
    ev_nom, ev_dec = R["eva_nominal"], R["eva_decompression"]
    eva_w = ev_nom["df"][ev_nom["df"]["med_mod"] == "eva"]
    eva_hr, eva_sp, eva_pio2 = eva_w["med_hr"].mean(), eva_w["med_spo2"].mean(), eva_w["eva_PIO2"].mean()
    al_nom = ev_nom["alarms"]
    eva_alarm_s = int(((al_nom.module == "eva") & (al_nom.code == "pio2_abs")).sum()) if len(al_nom) else 0
    dec = ev_dec["df"]
    after = dec[(dec["t"] > 4200) & (dec["med_mod"] == "eva")]
    dec_sp_min, dec_hr_max, dec_pio2 = after["med_spo2"].min(), after["med_hr"].max(), after["eva_PIO2"].mean()
    dec_loc = float(dec[dec.med_state >= 3].t.min() - 4200)
    fat = R["eva_decompression_fatal"]["df"]
    dec_dead = float(fat[fat.med_state >= 4].t.min() - 4200)
    p_b, p_a = float(dec[dec.t == 4199].eva_P.iloc[0]), float(dec[dec.t == 4201].eva_P.iloc[0])
    baro_sim, baro_luca = barotrauma(p_b, p_a, 1.0), barotrauma(350, 50, 0.2)
    fib = R["fibrillation"]["df"]
    fib_w = fib[(fib.t > 4300) & (fib.t < 5100)]
    alt_p350, alt_p50 = isa_altitude_m(350), isa_altitude_m(50)
    st_end = dd.iloc[-1]

    spo2_luca_eva = spo2_from_pio2(pio2(350, 28))
    pio2_luca_eva = pio2(350, 28)
    wk = lambda n, c: float(dd[(dd["tod"] >= 7) & (dd["tod"] < 12)][f"{n}_{c}"].mean())  # noqa: E731
    ranges = {k: (min(dd[f"{n}_{k}"].min() for n in NPCS), max(dd[f"{n}_{k}"].max() for n in NPCS)) for k in METRICS}

    atm_rows = atmosphere_monitor_summary(day, "Stazione 758 mmHg, 21 % O2 (adottata)") + atmosphere_monitor_summary(daym, "Habitat Marte 70.3 kPa, 26.5 % O2 (confronto)")
    ppo2_mars = float(dd["hab_P"].mean() * dd["hab_o2pct"].mean() / 100)

    scope = [
        "## A cosa serve",
        "Questo documento mostra quali dati producono i 4 astronauti simulati (NPC) in una giornata normale e in 11 situazioni particolari "
        "(scenari). Serve a controllare se i valori sono realistici e se ogni situazione e' rappresentata correttamente. Il modello non e' "
        "validato: dove manca una fonte il numero e' una nostra stima, marcata ESTIMATE, e chiediamo di correggerla.",
        "## Cosa chiediamo di verificare",
        "1) Giornata normale (una pagina per astronauta): i valori e il loro andamento nelle varie attivita' sono plausibili?",
        "2) Scenari (una pagina ciascuno): l'episodio modifica i parametri nel modo giusto, per intensita' e durata?",
        "3) Ambiente e assunzioni (pagine 2-4): le ipotesi sul luogo e sulla tuta sono accettabili?",
        "4) Incongruenze trovate nel brief e domande aperte (ultime pagine): servono le sue risposte per chiudere il modello.",
        "## Come leggere i numeri",
        "Ogni valore e' accompagnato da una fonte oppure dalla sigla ESTIMATE. Le fonti sono elencate nell'ultima pagina con il loro livello di "
        "affidabilita' (A = letta direttamente, B = letta solo tramite riassunto e da riverificare, E = nessuna fonte, stima nostra). "
        "Nei grafici l'area rosa e' il periodo in cui l'evento e' attivo; la linea punteggiata e' il valore indicato da Luca.",
        "## Astronauti simulati",
        "ASTRO_01 comandante (uomo, 75 kg), ASTRO_02 botanico (uomo, 74 kg, si allena sul tapis roulant T2), ASTRO_03 ingegnera (donna, 61 kg, "
        "episodio di fibrillazione), ASTRO_04 medico (donna, 65 kg, uscita EVA). Pesi, sesso, eta' e altezza sono quelli indicati da Luca nella sua revisione.",
    ]

    env_text = [
        "## Dove si svolge la simulazione",
        "Una stazione orbitale tipo ISS con 4 moduli pressurizzati collegati da portelli: habitat (60 m3, il volume indicato da Luca), laboratorio (40 m3), serra (30 m3) e airlock (15 m3). "
        "L'atmosfera e' quella dei profili 'STATION' di Luca: pressione 758 mmHg (101 kPa), 21 % di ossigeno, CO2 0.25 %, 21 C, umidita' 40 %, microgravita', giorno di 24 ore. "
        "Impianti simulati: depuratore di CO2, generatore di ossigeno, deumidificatore, regolatore di pressione e termostato. "
        "Perche' questo ambiente: tutti i calcoli di Luca presuppongono aria da livello del mare (altitudine 0, soglia di ossigeno 148 mmHg = 758 mmHg x 19.5 %), attrezzature ISS (T2, ARED, CEVIS), "
        "scenari 'a bordo ISS' e metabolismo ridotto del 10 % in microgravita'. L'habitat marziano (70.3 kPa, 26.5 % O2, PIO2 127 mmHg) e' stato simulato solo come confronto.",
        f"Con 758 mmHg e 21 % di ossigeno l'ossigeno inspirato (PIO2, vedi glossario) e' 149 mmHg e la SpO2 a riposo nel modello e' ~{spo2_station:.0f} %. Nell'habitat marziano sarebbe 127 mmHg, esattamente al limite NASA, con SpO2 ~{spo2_mars:.0f} %.",
        "## Fasi della missione considerate da Luca",
        "Dai suoi notebook le fasi sono quattro: decollo dalla Terra (calcolo energetico con forze G, miscela di ossigeno 'durante il decollo', strati atmosferici fino a 200000 piedi), "
        "permanenza in stazione (a riposo e in allenamento con T2, ARED, CEVIS), uscita EVA o in rover, e decompressione. La simulazione copre la stazione e la EVA (con la decompressione). "
        "Il decollo NON e' simulato: mancano un profilo di quota e di accelerazione, la pressione e la miscela della tuta durante l'ascesa e i vitali sotto forze G. "
        "Le funzioni basate sull'altitudine appartengono a decollo e tuta, non alla stazione.",
        "## Uscita nello spazio aperto (EVA)",
        "ASTRO_04 esce 30 minuti (10:00-10:30), preceduta da un'ora nell'airlock per la vestizione. (Le tute ISS reali, EMU, lavorano a 222 mmHg con O2 100 %.) Durante la EVA si trova in un volume separato di 12 m3 con atmosfera propria: "
        f"350 mmHg, CO2 0.15 %, supporto vitale proprio (depuratore, generatore di O2, regolatore di pressione, termostato). "
        f"Il brief indica il 28 % di ossigeno, ma con 350 mmHg si avrebbe PIO2 {pio2_luca_eva:.0f} mmHg, sotto il minimo NASA di 122 mmHg, con SpO2 attesa ~{spo2_luca_eva:.0f} % secondo la curva "
        "di letteratura. Abbiamo quindi ASSUNTO il 42 % di ossigeno (PIO2 127 mmHg, come l'habitat): e' una nostra ipotesi, da confermare. "
        "Il volume di 12 m3 e' molto piu' grande di una tuta (0.1-0.2 m3) e rende le dinamiche lente: e' mantenuto come nel brief.",
        "## Tempo e misure",
        "La simulazione avanza a passi di 1 secondo. Un giorno dura 24 ore; le routine sono in ore locali. Ogni grandezza ha un valore vero e uno misurato "
        "dal sensore (con rumore e ritardo): i grafici mostrano il valore vero, a meno che sia indicato diversamente. Gli allarmi sono calcolati sul valore vero. "
        "Un modulo di EVA genera allarmi solo mentre c'e' qualcuno dentro.",
        "## Routine giornaliera (ore locali)",
        "Tutti: sonno 22-6 (ASTRO_02 6.5), pasti 6-7, 12-13, 19-20, allenamento serale 17:00. ASTRO_01: lavoro in habitat; allenamento aerobico 30 min e di forza 60 min. "
        "ASTRO_02: lavoro in serra, tapis roulant T2 17:00-17:45. ASTRO_03: laboratorio e airlock, in habitat 11-12 (fibrillazione 11:10-11:25). "
        "ASTRO_04: laboratorio, vestizione 9-10, EVA 10-10:30, recupero in airlock, lavoro in laboratorio.",
    ]

    guide = [
        "## Come leggere i grafici",
        "Pagine 'giornata normale' (una per astronauta). Asse orizzontale: ora locale del giorno simulato, da 6 alle 6 del giorno dopo (i valori oltre 24 sono il giorno successivo). "
        "In alto, la striscia colorata indica l'attivita' in corso (sonno, pasto, lavoro, riposo, esercizio aerobico o di forza, recupero). Sotto, un pannello per ogni vitale: "
        "FC in battiti al minuto (circa 50 nel sonno, 70 a riposo, 140 sotto sforzo); SpO2 in % (saturazione dell'ossigeno nel sangue, normale 95-100); frequenza respiratoria in atti al minuto; "
        "HRV (RMSSD) in millisecondi, piu' e' alta piu' il battito e' variabile e rilassato; temperatura cutanea in gradi C. L'ultimo pannello mostra il modulo in cui si trova. "
        "La linea punteggiata e' il valore indicato da Luca.",
        "Pagina 'ambiente della giornata'. Asse orizzontale: ora locale. Asse verticale: la grandezza indicata nel titolo con la sua unita' (mmHg per le pressioni, C, %). "
        "La linea tratteggiata e' il limite di sicurezza NASA: superarlo fa scattare un allarme.",
        "Pagine degli scenari (una per evento). Asse orizzontale: ora locale. Ogni pannello mostra una grandezza (titolo con unita'); l'area rosa e' il periodo in cui l'evento e' attivo. "
        "La tabella sotto riporta il valore medio nei 30 minuti prima dell'evento, il minimo e il massimo durante, e la media nei 30 minuti dopo. A destra della tabella gli allarmi NASA scattati (con orari) "
        "e le etichette che il simulatore scrive nei dati ('nominal' oppure il nome dell'evento).",
        "Curva SpO2 e ECG. Curva SpO2: asse orizzontale = PIO2 (ossigeno inspirato, mmHg), asse verticale = SpO2 stazionaria in %; i punti sono i dati usati dal modello. "
        "ECG: asse orizzontale = i 140 campioni di un battito, asse verticale = ampiezza normalizzata; blu = battito normale (label 1.0), rosso = anomalo (label 0.0).",
    ]

    luca_inputs = pd.DataFrame([
        ["Critical_condition_monitor, cella 1: monitor ipossia", "Decollo / ascesa e tuta EVA ('altitudine equivalente della tuta')", "altitudine in metri",
         "NON simulata", "Derivabile dalla PIO2 o dalla pressione della tuta (incongruenza 1)"],
        ["Critical_condition_monitor, cella 2: miscela O2 minima", "Decollo (commento nel codice) e tuta EVA", "altitude_feet, oxygenperc (% O2 della miscela)",
         "% O2 del modulo disponibile; altitudine no", "Come sopra"],
        ["Critical_condition_monitor, cella 3: barotrauma", "Decompressione di cabina o tuta (EVA)", "pressione iniziale, pressione attuale, tempo (s)",
         "Pressione del modulo a 1 campione/s", "Passo di 1 s: la caduta in 0.2 s non e' risolvibile"],
        ["Critical_condition_monitor, cella 4: strati atmosferici", "Ascesa e EVA ad alta quota (fino a 200000 piedi)", "altitude_feet",
         "NON simulata (temperatura esterna, radiazioni)", "Fuori dalla simulazione attuale"],
        ["Critical_condition_monitor, cella 5: atmosfera della stazione", "Stazione", "num_astronauti, volume_modulo_m3, o2/co2 %, pressione, in_allenamento, eclss_attivo",
         "Tutti disponibili per modulo e istante", "num_astronauti = persone nel modulo; eclss_attivo = depuratore non guasto"],
        ["ECG IMPROVEMENTFINAL: monitor_astronaut_live", "Tutte le fasi", "single_raw_ecg (140 campioni), already_normalized",
         "Riga fissa del dataset per astronauta", "Non generato dai vitali; etichetta legata all'evento"],
        ["ENERGY_INTAKE, cella 1: lancio del razzo", "DECOLLO dalla Terra (forze G)", "heart_rate, peso_kg, durata_minuti, allarme ECG, score",
         "NON simulata: nessuna fase di lancio", "Domanda 13"],
        ["ENERGY_INTAKE, cella 2: stazione 'statica'", "Stazione, lavoro o riposo", "heart_rate, peso_kg, durata, allarme ECG, score",
         "FC, peso disponibili; MAE dipende dal modello ECG", "Metabolismo basale -10 % in microgravita' (nel nostro modello non applicato)"],
        ["ENERGY_INTAKE, cella 3: allenamento ISS", "Stazione, esercizio con T2, ARED o CEVIS", "heart_rate, peso_kg, durata, macchinario, allarme ECG, score",
         "Macchinario non ancora nei dati", "Usiamo T2 per l'aerobico di ASTRO_02, ARED per la forza (ipotesi)"],
        ["ENERGY_INTAKE, cella 4: EVA / rover", "EVA", "heart_rate, peso_kg, durata, oxygen_perc (= SpO2), allarme ECG, score",
         "FC, SpO2 disponibili", "SpO2 < 95 % / < 90 % aumenta il costo energetico del 15 % / 30 %"],
        ["ENERGY_INTAKE, cella 5: reintegrazione", "STATION oppure OUTSIDE", "scenario, durata, heart_rate, peso, sex, kcal e acqua giornaliere",
         "scenario e sex disponibili; kcal e acqua giornaliere NO", "Serve un consumo di cibo e acqua simulato"],
        ["stress-level-detection", "Non specificata", "colonne di Stress-lysis.csv (es. passi)", "Il CSV e' arrivato (umidita', temperatura, passi, stress): i passi non sono simulati", "Domanda 12"],
    ], columns=["Sezione dei dati di Luca", "Fase di missione", "Ingressi", "Disponibile dalla simulazione?", "Nota"])

    limits = pd.DataFrame([
        ["PIO2 - ossigeno inspirato", "media su 1 h >= 127 mmHg; mai sotto 122 mmHg; sopra 356 = avviso", "Pressione parziale dell'O2 nell'aria inspirata = (pressione totale - 47 mmHg di vapore acqueo) x frazione di O2. Determina quanto O2 arriva al sangue.", "Sotto il limite l'ossigenazione cala (SpO2)"],
        ["ppCO2 - anidride carbonica", "media su 1 h <= 3 mmHg", "Pressione parziale della CO2 nell'aria (0.4 % a 758 mmHg). Nello spazio i sintomi compaiono gia' a 3.5 mmHg.", "Mal di testa, respiro piu' frequente"],
        ["Pressione totale", "tra 34.5 e 103 kPa (259-772 mmHg)", "Pressione dell'aria del modulo.", "Troppo bassa o troppo alta e' pericoloso"],
        ["Temperatura", "tra 18 e 27 C", "Temperatura dell'aria.", "Comfort e termoregolazione"],
        ["Umidita' relativa", "tra 25 e 75 %", "Vapore acqueo rispetto alla saturazione.", "Comfort, condensa"],
    ], columns=["Grandezza", "Limite NASA-STD-3001", "Cosa significa", "Perche' conta"])

    def rg(k, f="{:.0f}"):
        return f"{f.format(ranges[k][0])} - {f.format(ranges[k][1])}"

    variables = pd.DataFrame([
        ["FC (hr)", "bpm", "Battiti al minuto", "Riposo per persona + sforzo (MET) + ambiente + fase del sonno + ritmo circadiano + febbre, disidratazione, microgravita'; ritardo 40 s salita, 65 s discesa", rg("hr")],
        ["SpO2 (spo2)", "%", "Saturazione di ossigeno nel sangue", "Curva dalla PIO2 [P1]; scostamenti degli episodi", rg("spo2", "{:.1f}")],
        ["Freq. respiratoria (resp_rate)", "atti/min", "Respiri al minuto", "14 a riposo (12 nel sonno, varia con la fase) + 1.5 per MET + CO2 + febbre", rg("rr")],
        ["HRV (hrv_rmssd)", "ms", "Variabilita' del battito (RMSSD)", "Per persona (sesso, eta'), scende con la FC; in AF dagli RR irregolari", rg("hrv")],
        ["Temperatura cutanea (skin_temp_c)", "C", "Temperatura della pelle (polso)", "33.5 + 0.05 per MET + sonno + ambiente", rg("skin", "{:.1f}")],
        ["Temperatura centrale (core_temp_c)", "C", "Temperatura interna del corpo", "36.8 + ritmo circadiano (+-0.4) + calore dello sforzo + febbre + disidratazione", rg("core", "{:.1f}")],
        ["Stato di salute (health_state)", "0-4", "0 ok, 1 sintomi, 2 compromesso, 3 incosciente, 4 morto", "Dose di ipossia, CO2 e calore (pagina del modello)", rg("state")],
        ["Acqua persa (dehydration_pct)", "% massa", "Deficit di acqua corporea", "Sudore dallo sforzo meno reidratazione (2 h); disidratazione da evento", rg("dehyd", "{:.1f}")],
        ["Fase del sonno (sleep_stage)", "codice", "0 veglia, 1 N1, 2 N2, 3 N3, 5 REM", "Ipnogramma a cicli di 90 minuti dall'inizio del sonno", "0 - 5"],
        ["Intervallo RR (rr_interval_ms)", "ms", "Tempo tra due battiti consecutivi", "Estratto attorno a 60000/FC con la variabilita' dell'HRV; irregolare in AF", rg("rrint")],
        ["Ritmo (rhythm)", "0/1", "1 = fibrillazione atriale in corso", "Dall'evento 'arrhythmia: af'", "0 - 1"],
        ["Nausea (nausea)", "0-3", "Gravita' del mal di spazio", "Livello della persona per il giorno di missione; evento", "0 - 3"],
        ["MET", "-", "Intensita' dell'attivita' (1 = riposo)", "Dalla routine: sonno 0.9, lavoro 1.45, esercizio 7, EVA 7.2; da incosciente e' 1", "0.9 - 7"],
        ["Attivita' e modulo", "-", "Cosa fa e dove si trova", "Dalla routine giornaliera", "-"],
        ["PIO2, ppCO2, P, T, UR del modulo", "mmHg, mmHg, mmHg, C, %", "Aria del modulo in cui si trova", "Fisica dei gas: respirazione degli astronauti (zero se morto), impianti, guasti", f"hab: PIO2 {dd['hab_PIO2'].min():.0f}-{dd['hab_PIO2'].max():.0f}, ppCO2 {dd['hab_ppCO2'].min():.1f}-{dd['hab_ppCO2'].max():.1f}"],
        ["Misura dei sensori", "come sopra", "Valore letto dal sensore", "Valore vero + rumore + ritardo; i guasti dei sensori non sono simulati in questi scenari", "-"],
        ["Etichetta anomalia (is_anomaly, anomaly_type)", "-", "Vale 'fault attivo' per ogni riga di dati", "Dall'evento attivo; fuori dagli eventi = 'nominal'. Lo stato di salute e' un'etichetta a parte", "-"],
    ], columns=["Variabile", "Unita'", "Cosa rappresenta", "Come viene prodotta", "Intervallo nel giorno normale"])

    model_text = [
        "## Come nascono i vitali",
        "Ogni astronauta ha un valore di riferimento a riposo che dipende da sesso, eta' e massa (pagina 'Persone simulate'). Su quello si sommano gli effetti: lo sforzo (piu' MET, piu' FC e respiro), "
        "l'ambiente (poco ossigeno = SpO2 piu' bassa e FC piu' alta; CO2 alta = respiro piu' frequente), la fase della giornata (sonno: FC -20 %, HRV piu' alta; di giorno la FC segue un ritmo circadiano di +-3 bpm con picco alle 15) "
        "e lo stato del corpo (febbre, disidratazione, microgravita'). Il valore vero si avvicina al valore obiettivo con ritardo: la FC sale con costante di tempo ~40 s e scende in ~65 s.",
        "## Stato di salute e coscienza (nuovo)",
        "Ogni astronauta ha uno stato: 0 ok, 1 sintomi, 2 compromesso (non puo' piu' agire), 3 incosciente, 4 morto. Lo stato segue una 'dose' di esposizione che ogni secondo aumenta di 1 diviso il tempo di coscienza utile "
        "(il tempo dopo il quale una persona non sa piu' reagire, tabella FAA [P21]) nelle condizioni di quel momento. Esempio: a PIO2 70 mmHg (18000 piedi) il tempo e' 25 minuti, a 8 mmHg (quasi vuoto) 6-9 secondi. "
        "La dose conta ipossia (PIO2), CO2 alta (perdita di coscienza solo sopra 50 mmHg, 7-10 % a pressione di mare [P22]) e calore (temperatura centrale sopra 39.5 C). Soglie sulla dose: 0.25 sintomi, 1 compromesso, 1.5 incosciente, 30 morto. "
        "Quando l'esposizione finisce la dose decade (costante 10 minuti) e l'astronauta si riprende. Dopo una decompressione rapida il tempo e' dimezzato [P21]. Tutte le soglie sono ESTIMATE, costruite sulla tabella FAA.",
        "## Conseguenze dello stato",
        "Incosciente: l'NPC smette di lavorare (MET 1, scambi di gas a riposo), con ipossia grave la FC scende (bradicardia) e il respiro rallenta. Morto: FC, SpO2, respirazione e HRV vanno a zero (costanti 30-60 s), "
        "gli scambi di gas si fermano e la temperatura del corpo si porta a quella della stanza. La morte e' OPZIONALE: parametro 'death_enabled' (falso di default; per uno scenario si imposta con 'physiology_overrides'). "
        "Con la morte disabilitata la dose si ferma appena sotto la soglia di morte e lo stato massimo e' 'incosciente'.",
        "## Altri meccanismi (nuovi)",
        "Persone: frequenza massima 208 - 0.7 x eta' [P13]; FC a riposo per persona da Luca (58, 56, 62, 60 bpm); HRV a riposo piu' alta nelle donne (+5 ms) e in calo con l'eta' [P14]; VO2max per persona da Luca (50, 54, 45, 47 ml/kg/min). "
        "Circadiano e sonno: ritmo di FC e temperatura centrale [P15]; ipnogramma deterministico a cicli di 90 minuti (N3 10-20 %, REM 20-25 % [P16]) che modifica FC e respiro nel sonno. "
        "Temperatura e acqua: la temperatura centrale cresce con lo sforzo e con la febbre; il sudore (da MET) riduce l'acqua del corpo, che si recupera bevendo (costante 2 h); la disidratazione aumenta la FC di 3 bpm per 1 % di massa persa [P17]. "
        "Microgravita': FC +3.4 bpm e HRV -10 % a regime [P18]; mal di spazio nei primi giorni, con gravita' per persona estratta dalla distribuzione Shuttle [P19] (le persone sono al giorno 30 di missione, quindi adattate). "
        "Ritmo: per ogni battito si estrae un intervallo RR attorno a 60000/FC; nel ritmo sinusale la variabilita' riproduce l'HRV, in fibrillazione l'RR e' irregolare [P20].",
        "## Cosa il modello non fa",
        "Non simula: sincope senza ipossia, traumi, perdita di massa ossea e muscolare, farmaci, discesa della SpO2 da sforzo, ECG generato dai vitali (l'ECG resta una riga fissa del dataset), "
        "reazioni dell'astronauta agli allarmi (fuori dallo scopo del progetto), il decollo dalla Terra.",
    ]

    incong = [
        "## Incongruenze nel brief ricevuto",
        "Per ciascuna: cosa dice il brief, cosa risulta dai calcoli e perche' conta. Le domande corrispondenti sono nell'ultima sezione.",
        f"1) Altitudine e pressione. Il brief associa 350 mmHg a 3000 m e 50 mmHg a 7000 m. In atmosfera standard 350 mmHg corrispondono a ~{alt_p350:,.0f} m e 50 mmHg a ~{alt_p50 / 1000:,.0f} km. "
        "Nel notebook l'altitudine e' l'altitudine equivalente della tuta (o la quota del decollo) e guida le regole di ipossia e di O2 minimo: con 3000 m l'esito e' 'condizioni stabili', con la quota che la pressione implica sarebbe 'pericolo'.",
        f"2) Ossigeno della tuta. 350 mmHg e 28 % O2 danno PIO2 {pio2_luca_eva:.0f} mmHg (limite NASA 122) e, secondo la curva di letteratura [P1], SpO2 ~{spo2_luca_eva:.0f} %; il brief indica SpO2 94 %. "
        "Una tuta reale usa 222 mmHg con O2 100 % (PIO2 ~175 mmHg) [P11]; la proposta NASA per Marte e' 8.2 psia (424 mmHg) con 34 % O2 (PIO2 128 mmHg, non validata). Abbiamo assunto il 42 % (PIO2 127).",
        f"3) Emergenza EVA. A 50 mmHg e 20 % O2 la PIO2 e' ~{pio2(50, 20):.1f} mmHg, praticamente vuoto. Il brief stesso indica perdita di coscienza in 9-15 s; la letteratura [P1] riporta 0-15 s a PIO2 28 mmHg dopo decompressione rapida. "
        f"FC 172 e SpO2 88 % descrivono invece una persona ancora cosciente. Nel modello la FC parte da 172 bpm e resta fissa, l'astronauta perde coscienza dopo {dec_loc:.0f} s, la SpO2 scende fino a {dec_sp_min:.0f} % e, con la morte abilitata, il decesso avviene dopo {dec_dead:.0f} s.",
        f"4) Passo temporale. La caduta 350->50 mmHg in 0.2 s avviene in un solo passo di simulazione (1 s). Applicando la regola barotrauma ai dati simulati il risultato e' '{baro_sim}', con i valori del brief (0.2 s) e' '{baro_luca}'. "
        "Per rilevare l'esplosiva servono passi <= 0.1 s attorno all'evento o un campo che dichiari la durata.",
        "5) Atmosfera della stanza. ASTRO_02 e ASTRO_03 sono indicati con 20.8 % O2 e 0.38 % CO2, ASTRO_01 con 21.0 % e 0.25 %, tutti nella stessa stanza (3 astronauti, 60 m3). Nello stesso volume e nello stesso istante l'aria e' una sola. "
        f"0.38 % di CO2 a 758 mmHg e' ~2.9 mmHg, a ridosso del limite NASA di 3 mmHg. Nella simulazione la CO2 dell'habitat non supera {dd['hab_co2pct'].max():.2f} %.",
        "6) Dati anagrafici. ASTRO_02 e' descritto 'uomo' nel brief (e Luca elenca 2 uomini e 2 donne): ora e' uomo di 74 kg (confermato da Luca). Il blocco 'astro_4' compare due volte (il terzo e' ASTRO_03). Per ASTRO_02/03 'oxygenperc' e' 21 ma 'o2_perc_attuale' e' 20.8.",
        "7) Due tabelle di soglie. La funzione del notebook e il file monitor_parametri_spaziali.csv danno stati di ipossia e O2 minimo diversi alla stessa quota (pagina dedicata).",
        f"8) Fibrillazione. FC 150 e SpO2 93 % a riposo sono simili a un allenamento intenso (ASTRO_02: {bot_ex:.0f} bpm): su FC e SpO2 i due casi non si separano, serve l'ECG (label 0.0) e il contesto 'in_allenamento'. "
        "Nella fibrillazione l'HRV (RMSSD) tende ad aumentare [P9]: il modello genera RR irregolari (RMSSD ~85 ms, ESTIMATE nell'intervallo 80-250 ms [P20]).",
        f"9) Intensita' dell'allenamento. Il catalogo di attivita' assegna 9.7 MET all'esercizio aerobico (FC ~180, 97 % del massimo); NASA riporta sessioni sul tapis roulant ISS al 66-75 % del picco di FC [P2]. Abbiamo usato 7.0 MET: FC media {bot_ex:.0f} bpm (brief: 142.5), circa 78 % del massimo.",
        "10) ECG. Il dataset ha 100 righe da 140 campioni (60 normali = label 1.0, 40 anomale = label 0.0). Ogni NPC riceve una riga fissa; l'ECG non viene generato dai vitali. L'etichetta andrebbe legata all'evento (0.0 durante fibrillazione ed emergenza).",
    ]

    questions = [
        "## Risposte di Luca (recepite)",
        "1, 2, 4, 5) Confermati: stazione a livello del mare (niente Marte), tuta a 350 mmHg con 42 % di O2 e volume di 12 m3, la PIO2 e' la grandezza di riferimento (l'altitudine e' solo un confronto), valgono le tabelle PIO2 e ppO2 del simulatore. "
        "6) Il controllo sull'ossigeno in cabina (ppO2 sotto 148 mmHg, O2 sopra 23.5 %) vale solo per la cabina e non per la tuta: il simulatore usa gia' solo la PIO2 (limiti 122 e 127 mmHg). "
        "3) I valori del brief (FC 172, SpO2 88 %) sono i valori iniziali subito dopo la rottura: ora la decompressione parte da li' e poi peggiora. "
        "7) Cinque stati confermati; dopo la morte la serie vale 0 e le righe hanno l'etichetta 'dead' (MORTO). "
        "8) Anagrafica aggiornata: ASTRO_01 uomo 42 anni, 178 cm, 75 kg, FC a riposo 58, VO2max 50; ASTRO_02 uomo 35 anni, 180 cm, 74 kg, 56, 54; ASTRO_03 donna 36 anni, 168 cm, 61 kg, 61, 45; ASTRO_04 donna 38 anni, 171 cm, 65 kg, 60, 47. "
        "9) Fibrillazione: valori clinici confermati; la SpO2 oscilla tra 91 e 94 %; gli intervalli RR non servono (l'ECG viene dalla forma d'onda completa del suo CSV). "
        "10, 11) Valori confermati (ampiezze circadiane, ipnogramma, perdita d'acqua e reidratazione); adattamento alla microgravita' dal giorno 10, mal di spazio dal giorno 1. "
        "Seconda tornata: sudore 5 g/min per MET sopra 2 (1.5 L/h a 7 MET, giusto per Luca); MET di palestra (7.0) ed EVA (7.2) invariati, perche' Luca considera le FC ottenute giuste per atleti che si allenano 2 ore al giorno; durante la decompressione la FC resta fissa a 172 bpm; la febbre e' assegnata ad ASTRO_01 (in cabina) per non avvicinarsi all'ipertermia. "
        "12) Stress-Lysis.csv ricevuto (umidita', temperatura, passi, livello di stress 0-2). I suoi moduli usano: ECG (140 campioni), SpO2, peso, sesso, macchinario, luogo/scenario, durata e, dai sensori, pressione, O2, CO2 e dt; non servono FC, respirazione, HRV e temperature.",
        "## Ancora aperte",
        "Variabile 'passi' del modulo stress (il simulatore non la produce; temperatura del CSV forse in gradi Fahrenheit); decollo dalla Terra (13). "
        "Le sezioni numerate qui sotto sono le domande originali, gia' risposte sopra salvo quelle elencate in questo paragrafo.",
        "## Decisioni gia' prese (se non corrette da Luca)",
        "Gli NPC sono ASTRO_01 comandante, ASTRO_02 botanica, ASTRO_03 ingegnera, ASTRO_04 medico (confermato). L'ambiente e' la stazione (758 mmHg, 21 % O2). Per l'EVA usiamo 350 mmHg con 42 % di ossigeno invece di 28 %, perche' il valore del brief da' PIO2 sotto il limite NASA. "
        "L'esercizio aerobico e' fissato a 7.0 MET e la EVA a 7.2 MET (indicazione di Luca). La morte e' opzionale (disabilitata di default). Il comportamento reattivo degli astronauti (reazione agli allarmi) e' fuori dallo scopo: il progetto monitora la salute.",
        "## 1) Ambiente di riferimento: conferma stazione/livello del mare",
        "Contesto: abbiamo adottato l'ambiente dei suoi profili 'STATION' (758 mmHg, 21 % O2, microgravita'): e' coerente con altitudine 0, soglia ppO2 148 mmHg, macchinari ISS e metabolismo in microgravita'. "
        f"L'habitat marziano (70.3 kPa, 26.5 % O2) darebbe PIO2 127 mmHg e SpO2 a riposo ~{spo2_mars:.0f} %, contro ~{spo2_station:.0f} % della stazione. Ci serve: conferma che il modello di allerta lavora in ambiente ISS/livello del mare "
        "(e se mai servira' anche Marte, con quali soglie).",
        "## 2) Atmosfera e volume della tuta EVA",
        "Contesto: vedi incongruenza 2. Opzioni: 350 mmHg al 28 % (brief, PIO2 85, SpO2 attesa ~83 %), 350 mmHg al 42 % (nostra assunzione, PIO2 127), tuta EMU 222 mmHg con O2 100 %, tuta marziana 424 mmHg con 34 %. "
        "Il volume di 12 m3 e' un airlock/rover o una tuta (0.1-0.2 m3)? Ci serve: i valori reali che intende usare.",
        "## 3) Cosa deve produrre l'NPC durante l'emergenza EVA",
        f"Contesto: a 50 mmHg la PIO2 e' ~{pio2(50, 20):.1f} mmHg. Il modello ora simula la perdita di coscienza dopo {dec_loc:.0f} s (la FC parte da 172 bpm e resta fissa) e, se abilitata, la morte dopo {dec_dead:.0f} s; il brief indica FC 172 e SpO2 88 % e perdita di coscienza in 9-15 s. "
        "Ci serve: sono i valori iniziali dopo la rottura (da cui l'NPC peggiora) oppure a regime? Il tempo alla perdita di coscienza e quello alla morte sono accettabili?",
        "## 4) Altitudine",
        "Contesto: incongruenza 1. Assunzione attuale: l'altitudine non viene calcolata. Ci serve: quale grandezza considera 'vera' (pressione, PIO2 o altitudine) per le sue regole; proponiamo di derivare l'altitudine equivalente dalla PIO2.",
        "## 5) Quale tabella di soglie vale",
        "Contesto: incongruenza 7. Ci serve: la tabella corretta per stati di ipossia e O2 minimo richiesto.",
        "## 6) Significato di tempo_trascorso_secondi e criteri del monitor atmosfera",
        "Contesto: dal notebook, num_astronauti e' il numero di persone nel modulo e tempo_trascorso_secondi e' l'intervallo tra pressione iniziale e attuale (1.0 normale, 0.2 emergenza). "
        "La funzione di atmosfera allarma con ppO2 = P x %O2 sotto 148 mmHg (soglia da livello del mare). Con la stazione (758 x 21 % = 159) non scatta; con la tuta (350 x 42 % = 147) e con l'habitat marziano (140) scatta anche in condizioni normali. "
        "Il limite O2 > 23.5 % (rischio incendio) vale per una cabina ma scatta sempre in tuta (O2 28-42 %). Ci serve: conferma del significato di tempo_trascorso_secondi e quali criteri usare per l'ossigeno in cabina e in tuta (ppO2 oppure PIO2 con limite NASA 122-127 mmHg; limite di O2 alto solo per la cabina).",
        "## 7) Stati di salute: soglie e morte",
        "Contesto: abbiamo 5 stati (ok, sintomi, compromesso, incosciente, morto) guidati da una dose di ipossia, CO2 e calore costruita sul tempo di coscienza utile della FAA, con soglie nostre (0.25 / 1 / 1.5 / 30). "
        "La morte e' opzionale per scenario. Ci serve: sono questi gli stati che il suo modello di allerta deve riconoscere? Soglie e tempi realistici (perdita di coscienza, morte)? Nel dataset la serie dopo la morte deve continuare a zero, interrompersi o avere un'etichetta dedicata?",
        "## 8) Persone: eta', altezza, valori a riposo",
        "Contesto: usiamo FC a riposo 60 (uomini) e 64 (donne) con il comandante a 64, HRV 45 ms (+5 donne), massima 208 - 0.7 x eta'; eta' e altezza sono nostre stime (comandante 42, ingegnera 36, medico 38, botanica 34). "
        "Ci serve: eta', altezza, forma fisica reali e i valori a riposo per persona.",
        "## 9) Fibrillazione: valori clinici",
        "Contesto: FC 150 e SpO2 93 % sono nel brief; la respirazione +3 e l'irregolarita' degli RR (deviazione standard 15 % dell'RR medio, RMSSD ~85 ms) sono nostre stime. Ci serve: i valori clinici che considera corretti per FC, SpO2, HRV e respirazione, "
        "come la SpO2 misurata al polso viene disturbata dall'aritmia e se il modello ECG vuole in ingresso la serie degli intervalli RR (la forniamo come 'rr_interval_ms').",
        "## 10) Disidratazione, stress, nausea, febbre",
        "Contesto: la disidratazione, la febbre e il mal di spazio sono ora stati del corpo che seguono formule (3 bpm per 1 % di massa persa, 8.5 bpm per grado, gravita' dello Shuttle); lo stress resta un episodio imposto (nessuna fonte quantitativa). "
        "Ci serve: intervalli di FC, HRV, respirazione e temperatura per ciascun evento e la loro durata tipica; la perdita d'acqua (0.5 %/h) e la reidratazione (2 h) sono realistiche?",
        "## 11) Ritmo circadiano, sonno e microgravita'",
        "Contesto: FC +-3 bpm con picco alle 15, temperatura centrale +-0.4 C con minimo alle 4:30, ipnogramma a cicli di 90 minuti, e in orbita FC +3.4 bpm e HRV -10 %; gli astronauti sono al giorno 30 di missione (adattati). "
        "Ci serve: ampiezze corrette, e il giorno di missione in cui far partire gli scenari (nei primi 3 giorni compare il mal di spazio).",
        "## 12) Ingressi del modello di allerta",
        "Contesto: il simulatore produce FC, SpO2, respirazione, HRV, temperatura cutanea e centrale, intervallo RR, stato di salute (etichetta), ECG (riga del dataset) e ambiente, a 1 campione al secondo. I suoi moduli (pagina 'Dati che i moduli di Luca si aspettano') usano FC, SpO2, peso, sesso, macchinario, luogo, atmosfera e punteggio ECG, ma non respirazione, HRV e temperatura. "
        "Il modulo di stress usa un file (Stress-lysis.csv) che non abbiamo. Ci serve: il csv dello stress con le sue variabili (es. passi), e quali delle nostre variabili servono davvero al modello (lo stato di salute e' un'etichetta, non va dato in ingresso). "
        "Il macchinario (T2/ARED/CEVIS) va aggiunto ai dati: usiamo T2 per l'esercizio aerobico di ASTRO_02 e ARED per quello di forza.",
        "## 13) Decollo dalla Terra",
        "Contesto: i notebook considerano il decollo (calcolo energetico con forze G, miscela di ossigeno durante il decollo, strati atmosferici). La simulazione non ha questa fase. "
        "Ci serve: vuole uno scenario di decollo? In tal caso servono profilo di quota e di accelerazione nel tempo, pressione e miscela della tuta, durata e vitali attesi (FC > 140 nel suo calcolo energetico).",
        "## 14) Dati del brief da correggere",
        "ASTRO_02 e' uomo (come nel brief, 2 uomini e 2 donne)? I blocchi astro_4 sono due? Qual e' il valore corretto di ossigeno per ASTRO_02/03 (20.8 o 21)?",
    ]

    sources = pd.DataFrame([
        ["P1", "Curva SpO2 contro PIO2 e tempo di coscienza utile", "Hypoxic Hypoxia and Brain Function in Military Aviation, Tab. 2", "pmc.ncbi.nlm.nih.gov/articles/PMC8171399", "A"],
        ["P2", "Intensita' allenamento ISS (66-75 % del picco di FC)", "NASA OCHMO-TB-031 Exercise overview; studio ISS sull'esercizio", "nasa.gov/ochmo-tb-031-exercise-overview-2 ; pmc.ncbi.nlm.nih.gov/articles/PMC7434884", "B"],
        ["P3", "FC e VO2 proporzionali (effetto sforzo)", "Relationship between %HRR and %VO2R in treadmill exercise", "pubmed.ncbi.nlm.nih.gov/9502363", "B"],
        ["P4", "FC nel sonno 20-30 % sotto il riposo", "Cleveland Clinic, sleeping heart rate", "health.clevelandclinic.org/sleeping-heart-rate", "B"],
        ["P5", "Normali: respirazione 12-20/min, SpO2 96-100 %", "OpenStax Clinical Nursing Skills, 15.6", "openstax.org/books/clinical-nursing-skills/pages/15-6-respiration", "A"],
        ["P7", "Recupero FC dopo sforzo (tau 65 s)", "Exponential modelling of heart rate recovery after maximal exercise", "ijpp.com/exponential-modelling-of-heart-rate-recovery-after-a-maximal-exercise", "B"],
        ["P8", "Febbre: +8.5 bpm per grado C", "Fever and cardiac rhythm; Body temperature and heart rate", "pubmed.ncbi.nlm.nih.gov/2424378 ; journalfeed.org/?p=2902", "B"],
        ["P9", "Fibrillazione: RR irregolari, RMSSD piu' alto", "HRV in AF and hypertension (Eur J Clin Invest 2021)", "onlinelibrary.wiley.com/doi/full/10.1111/eci.13361", "B"],
        ["P10", "FC durante EVA (media 131-135 bpm, picchi ~162)", "NASA: Physical exertion and metabolic demand of EVA (NTRS 19910001262)", "ntrs.nasa.gov/citations/19910001262", "B"],
        ["P11", "Pressione e O2 delle tute (EMU 222 mmHg 100 % O2; Marte 8.2 psia 34 %)", "NASA EVA Operations, cap. 5.4; OCHMO-TB-037", "nasa.gov/wp-content/uploads/2023/03/gernhardt-eva-ops-chp-5.4-2013.pdf", "A/B"],
        ["P12", "Limiti e sintomi della CO2", "NASA OCHMO-TB-004 Carbon dioxide", "nasa.gov/wp-content/uploads/2023/12/ochmo-tb-004-carbon-dioxide.pdf", "A"],
        ["P13", "FC massima per eta' (208 - 0.7 x eta')", "Tanaka et al. 2001, Age-predicted maximal heart rate revisited", "pubmed.ncbi.nlm.nih.gov/11153730", "A"],
        ["P14", "Differenze di sesso: FC a riposo +4 bpm nelle donne, RMSSD +5 ms (20-45 anni)", "Altini (dati di sportivi); Lifelines Cohort; Koenig e Thayer 2016", "pmc.ncbi.nlm.nih.gov/articles/PMC7734556 ; lifelines.sites.kirra.nl", "B"],
        ["P15", "Ritmo circadiano di FC e temperatura (minimo di temperatura 03-05); ampiezze ESTIMATE", "Sleep 2013, circadian rhythm of heart rate in sleep stages", "pmc.ncbi.nlm.nih.gov/articles/PMC3825442", "B"],
        ["P16", "Architettura del sonno (N3 10-20 %, REM 20-25 %, cicli 90-120 min)", "Sleep Foundation; polisonnografia su 206 adulti sani", "sleepfoundation.org/how-sleep-works/deep-sleep ; pmc.ncbi.nlm.nih.gov/articles/PMC5886429", "B"],
        ["P17", "Disidratazione: +3 bpm e +0.12-0.25 C per 1 % di massa persa", "Revisione sull'esercizio al caldo", "pubmed.gov/24736771", "B"],
        ["P18", "Microgravita': FC +3.4 bpm, volume plasmatico -10-17 %, parasimpatico ridotto", "Effects of weightlessness on the cardiovascular system, meta-analisi 2024", "pmc.ncbi.nlm.nih.gov/articles/PMC11310543 ; PMC8773383", "B"],
        ["P19", "Mal di spazio: 67 % al primo volo (30 % lieve, 24 % moderato, 13 % severo), 2-3 giorni", "Space motion sickness during 24 flights of the Space Shuttle", "researchexperts.utmb.edu ; ntrs.nasa.gov/citations/20050000946", "B"],
        ["P20", "Intervalli RR in fibrillazione atriale (RMSSD 80-250 ms)", "Modello AFVP (PhysioNet); tesi BioGears, Univ. Washington", "pmc.ncbi.nlm.nih.gov/articles/PMC1820785 ; archive.physionet.org/physiotools/afvp", "B"],
        ["P21", "Tempo di coscienza utile contro quota; dimezzato dopo decompressione rapida", "FAA, hypoxia (airman education); tabella FAA AC 61-107B (da verificare)", "faa.gov/pilots/training/airman_education/topics_of_interest/hypoxia", "B"],
        ["P22", "CO2 ad alta concentrazione: 7-10 % svenimento in pochi minuti", "EPA appendice B (Schulte 1964, Lambertsen 1971)", "19january2021snapshot.epa.gov/.../co2appendixb.pdf", "B"],
        ["-", "Limiti di pressione, PIO2, T, UR usati come allarmi", "NASA-STD-3001 (via docs/reference/ambientmonitor)", "-", "A"],
        ["E", "Stress, nausea, ampiezze circadiane, soglie di dose (sintomi, perdita di coscienza, morte), SpO2 in AF, VO2max, eta' e altezza degli astronauti", "Nessuna fonte quantitativa trovata: stima nostra (ESTIMATE)", "-", "E"],
    ], columns=["Tag", "Cosa supporta", "Fonte", "Dove (URL abbreviato)", "Aff."])

    doc = Doc()
    text_page(doc, "ARES 3 - Dati prodotti dagli astronauti simulati: verifica", scope)
    text_page(doc, "Ambiente e assunzioni della simulazione", env_text)
    table_page(doc, "Glossario e limiti di sicurezza NASA usati come allarmi", limits,
               "Un 'allarme' nella simulazione significa che il valore VERO di un modulo ha superato uno di questi limiti (NASA-STD-3001, standard di salute e prestazioni degli equipaggi). "
               "Non e' una diagnosi sull'astronauta.", col_w=[0.15, 0.22, 0.45, 0.18])
    table_page(doc, "Variabili prodotte dalla simulazione", variables,
               "Gli intervalli sono quelli osservati in un giorno normale (4 astronauti). Gli scenari possono uscire da questi intervalli.",
               col_w=[0.17, 0.07, 0.19, 0.38, 0.19], cls="small")
    text_page(doc, "Come funziona il modello: vitali e stato di salute", model_text)

    # ---- time of useful consciousness used by the model
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.3))
    xs, ys = zip(*HYPOXIA_TUC[:-1])
    a1.semilogy(xs, ys, "o-", color="#1f77b4")
    for label, x in (("stazione 149", 149), ("EVA assunta / Marte 127", 127), ("limite NASA 122", 122), ("EVA di Luca 85", 85), ("quasi vuoto 8", 8)):
        a1.axvline(x, color="#999", ls=":", lw=0.8)
        a1.text(x + 1.5, 7, label, rotation=90, fontsize=7, va="bottom", ha="left")
    a1.set_xlim(0, 160)
    a1.set_xlabel("PIO2 (mmHg)")
    a1.set_ylabel("tempo di coscienza utile (s, scala log)")
    a1.set_title("Ipossia: tempo prima di non poter piu' agire [P21]", fontsize=9)
    cx, cy = zip(*CO2_TLOC)
    a2.semilogy(cx, cy, "o-", color="#d95f02")
    a2.axvline(3, color="k", ls="--", lw=0.8)
    a2.text(4.5, 70, "limite NASA 3 mmHg (solo sintomi)", rotation=90, fontsize=7, va="bottom", ha="left")
    a2.set_xlabel("ppCO2 (mmHg)")
    a2.set_ylabel("tempo alla perdita di coscienza (s, scala log)")
    a2.set_title("CO2: sotto 50 mmHg nessuna perdita di coscienza [P22]", fontsize=9)
    a2.set_xlim(0, 160)
    fig.tight_layout()
    doc.fig(fig, "Dose di esposizione: tempi usati dal modello",
            "Sinistra: asse orizzontale = PIO2, l'ossigeno inspirato in mmHg; asse verticale = secondi (scala logaritmica) dopo i quali l'astronauta non sa piu' reagire; i punti sono la tabella FAA da 18000 a 50000 piedi [P21] "
            "e le linee tratteggiate sono le PIO2 incontrate negli scenari. Destra: asse orizzontale = ppCO2 in mmHg, verticale = secondi alla perdita di coscienza (stima nostra dentro '7-10 % in pochi minuti' [P22]). "
            "Ogni secondo la dose aumenta di 1/tempo; con PIO2 oltre 100 mmHg (cioe' tutte le linee a destra) la dose non cresce mai, quindi nell'aria della stazione, nell'habitat marziano e nella EVA assunta (127 mmHg) nessuno perde coscienza.",
            intro='<p>Questo e\' il cuore dello stato di salute: piu\' l\'ossigeno e\' basso (o la CO2 alta), piu\' in fretta la dose sale verso le soglie 0.25 sintomi, 1 compromesso, 1.5 incosciente, 30 morto (solo se abilitata).</p>')

    # ---- people
    ind = day["ind"]
    ind_df = pd.DataFrame([[ALIAS[n], n, ind[n]["sex"], f"{ind[n]['age']:.0f}", f"{ind[n]['height']:.0f}", f"{ind[n]['mass']:.1f}", f"{ind[n]['hr_rest']:.0f}",
                            f"{ind[n]['hr_max']:.0f}", f"{ind[n]['met_max'] * 3.5:.0f}", f"{ind[n]['hrv_rest']:.0f}",
                            ["nessuna", "lieve", "moderata", "severa"][ind[n]["sms"]]] for n in NPCS],
                          columns=["Luca", "NPC", "Sesso", "Eta' (anni)", "Altezza (cm)", "Massa (kg)", "FC riposo (bpm)", "FC massima (bpm)",
                                   "VO2max (ml/kg/min)", "HRV riposo (ms)", "Predisposizione al mal di spazio"])
    table_page(doc, "Persone simulate e parametri individuali", ind_df,
               "Eta', altezza e massa sono quelli indicati da Luca. Le altre colonne sono calcolate: FC massima = 208 - 0.7 x eta' [P13]; "
               "FC a riposo e VO2max forniti da Luca per ciascuna persona; HRV a riposo 45 ms (+5 donne, -0.4 per anno sopra i 30) [P14]; "
               "predisposizione estratta a caso (seed fisso) dalla distribuzione Shuttle [P19]: dopo il giorno 3 di missione non ha effetto.",
               intro="Parametri che differenziano i quattro astronauti. Vengono usati dal modello fisiologico al posto di valori uguali per tutti.")
    text_page(doc, "Come leggere i grafici", guide)
    table_page(doc, "Dati che i moduli di Luca si aspettano e dove li prendiamo", luca_inputs,
               "Elenco ricavato dai notebook di Luca (ECG IMPROVEMENTFINAL, Critical_condition_monitor, ENERGY_INTAKE_HYDRATION, stress-level-detection). "
               "Nota sui nomi: 'oxygen_perc' e' la SpO2 (sangue), 'oxygenperc' e' la percentuale di ossigeno della miscela respirata.",
               col_w=[0.21, 0.19, 0.25, 0.17, 0.18], cls="small")
    params = pd.DataFrame([
        ["FC a riposo e VO2max", "per persona, da Luca: FC 58/56/62/60 bpm, VO2max 50/54/45/47", "valori forniti dal bioingegnere", "A"],
        ["FC massima", "208 - 0.7 x eta'", "Tanaka [P13]", "A"],
        ["FC nel sonno", "80 % del riposo, modulata dalla fase (N3 -7 %, REM +7 %)", "20-30 % piu' bassa [P4]; fasi [P16], entita' ESTIMATE", "B/E"],
        ["FC diurna (circadiano)", "+-3 bpm, picco alle 15:00", "[P15]; ampiezza ESTIMATE", "E"],
        ["FC sotto sforzo", "riposo + (massima - riposo) x (MET-1)/(MET max - 1)", "FC e VO2 lineari [P3]", "B"],
        ["FC recupero / salita", "tau 65 s / 40 s", "[P7] / ESTIMATE", "B/E"],
        ["FC con poco ossigeno", "+0.5 bpm per mmHg sotto PIO2 127, massimo +40", "ESTIMATE", "E"],
        ["SpO2", "98 % a riposo; scende secondo la curva PIO2->SpO2", "[P1] tra 70 e 99 mmHg, sotto ESTIMATE; 96-100 % [P5]", "A/E"],
        ["Freq. respiratoria", "14/min (sonno 12) + 1.5 per MET", "12-20/min [P5]; incremento ESTIMATE", "A/E"],
        ["HRV (RMSSD)", "45 ms (+5 donne), scende con la FC", "[P14]; resto ESTIMATE", "B/E"],
        ["Temperatura centrale", "36.8 C +-0.4 (minimo 4:30) + 0.15 per MET", "[P15]; ampiezze ESTIMATE", "E"],
        ["Temperatura cutanea", "33.5 C + 0.05 per MET, +0.6 nel sonno", "ESTIMATE", "E"],
        ["Disidratazione", "FC +3 bpm, T centrale +0.2 C per 1 % di massa persa; sudore 5 g/min per MET sopra 2 (1.5 L/h a 7 MET)", "[P17]; sudore ESTIMATE", "B/E"],
        ["CO2 -> FC / respirazione", "+1 bpm e +1.5/min per mmHg sopra 2", "ESTIMATE (sintomi a 3.5 mmHg [P12])", "E"],
        ["Febbre", "+8.5 bpm per C, respirazione +2 per C", "[P8]; respirazione ESTIMATE", "B/E"],
        ["Fibrillazione", "FC 150, SpO2 93 (brief); RR con SD 15 % (RMSSD ~85 ms)", "FC>100-110 [P9]; RMSSD 80-250 ms [P20]; SpO2 ESTIMATE", "B/E"],
        ["Microgravita'", "FC +3.4 bpm, HRV -10 %; mal di spazio fino al giorno 3", "[P18], [P19]; effetti per livello ESTIMATE", "B/E"],
        ["Perdita di coscienza e morte", "dose = somma di 1/tempo di coscienza utile; soglie 1.5 e 30", "tabella FAA [P21], CO2 [P22]; soglie ESTIMATE", "B/E"],
        ["Stress", "FC +10, HRV x0.6, respirazione +2", "nessuna fonte quantitativa", "E"],
    ], columns=["Grandezza", "Valore nel modello", "Fonte / nota", "Aff."])
    table_page(doc, "Parametri del modello e loro fonti", params,
               "I tag [P1]-[P22] sono spiegati con il titolo della fonte nell'ultima pagina. Aff.: A letta direttamente, B letta tramite riassunto da riverificare, E = ESTIMATE, nessuna fonte.",
               col_w=[0.18, 0.36, 0.38, 0.08], cls="small")

    # ---- one page per NPC: normal day
    for n in NPCS:
        fig, axes = plt.subplots(6, 1, figsize=(11, 6.4), sharex=True, gridspec_kw={"height_ratios": [0.35, 1.7, 1.1, 1.1, 1.1, 1.3]})
        h = hours(day)
        activity_strip(axes[0], day, n)
        axes[0].set_ylabel("attivita'", fontsize=6, rotation=0, labelpad=26)
        for ax, k in zip(axes[1:5], ["hr", "spo2", "rr", "hrv"]):
            ax.plot(h, day["df"][f"{n}_{k}"], color=COL[n], lw=0.9)
            ax.set_ylabel(METRICS[k][0], fontsize=7)
            ax.tick_params(labelsize=7)
        axes[1].axhline(LUCA[n]["hr"], color="k", ls=":", lw=0.8)
        axes[1].text(h[0] + 0.1, LUCA[n]["hr"], f" Luca {LUCA[n]['hr']}", fontsize=6, va="bottom")
        axes[2].axhline(LUCA[n]["spo2"], color="k", ls=":", lw=0.8)
        axes[2].text(h[0] + 0.1, LUCA[n]["spo2"], f" Luca {LUCA[n]['spo2']}", fontsize=6, va="bottom")
        ax = axes[5]
        ax.plot(h, day["df"][f"{n}_core"], color=COL[n], lw=0.9, label="centrale")
        ax.plot(h, day["df"][f"{n}_skin"], color=COL[n], lw=0.9, ls="--", label="cutanea")
        ax.legend(fontsize=6, loc="center right", frameon=False)
        ax.set_ylabel("Temperatura (C)", fontsize=7)
        ax.tick_params(labelsize=7)
        ax.set_xlabel("ora locale (h, oltre 24 = giorno dopo)", fontsize=8)
        ax.set_xlim(h[0], h[-1])
        handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in ACT_COL.values()]
        fig.legend(handles, list(ACT_COL), ncol=8, fontsize=6, loc="upper right", frameon=False)
        fig.tight_layout(rect=(0, 0, 1, 0.97))
        mods = ", ".join(dict.fromkeys(day["df"][f"{n}_mod"]))
        i = ind[n]
        doc.fig(fig, f"{NAME[n]} - giornata nominale",
                "Asse orizzontale: ora locale (da 6 a 30; i valori oltre 24 sono il giorno dopo). Striscia in alto: attivita' in corso (legenda a destra). Pannelli, dall'alto: FC in battiti al minuto; SpO2 in % (normale 95-100); "
                "frequenza respiratoria in atti al minuto; HRV (RMSSD) in millisecondi, piu' alta = battito piu' variabile e rilassato; temperature in gradi C (continua = centrale, tratteggiata = cutanea). "
                "La linea punteggiata e' il valore di FC e SpO2 indicato da Luca per questo astronauta.",
                intro=f'<p>{esc(ALIAS[n])}: sesso {i["sex"]}, {i["age"]:.0f} anni (stima), {i["mass"]:.1f} kg; FC a riposo {i["hr_rest"]:.0f}, massima {i["hr_max"]:.0f} bpm. '
                      f'Ambiente: stazione, 758 mmHg, 21 % O2. Moduli visitati nella giornata: {esc(mods)}.</p>')

    # ---- per activity table with reference ranges
    refs = {"sleep": dict(hr=(40, 60), spo2=(95, 100), rr=(10, 16)),
            "work": dict(hr=(60, 100), spo2=(95, 100), rr=(12, 20)),
            "exercise_aerobic": dict(hr=(122, 139), spo2=(95, 100), rr=(16, 40))}
    refs["meal"] = refs["rest"] = refs["recovery"] = refs["work"]
    rows = []
    for _, r in sa.iterrows():
        ref = refs.get(r.act)
        flags = []
        if ref:
            for k in ("hr", "spo2", "rr"):
                lo, hi = ref[k]
                if not lo <= r[k] <= hi:
                    flags.append(f"{k} fuori {lo}-{hi}")
        rows.append([ALIAS[r.npc], r.npc, r.act, f"{r.minutes:.0f}", f"{r.hr:.0f}", f"{r.spo2:.1f}", f"{r.rr:.1f}", f"{r.hrv:.0f}",
                     f"{r.skin:.1f}", f"{r.core:.1f}", "OK" if ref and not flags else ("; ".join(flags) if flags else "-")])
    table_page(doc, "Media per attivita' nel giorno nominale e verifica sui riferimenti", pd.DataFrame(
        rows, columns=["Luca", "NPC", "Attivita'", "min", "FC", "SpO2", "FR", "HRV", "T cut.", "T centr.", "Verifica"]),
        "Riferimenti (ESTIMATE di lavoro): sonno FC 40-60 [P4]; veglia a riposo FC 60-100, SpO2 95-100, FR 12-20 [P5]; esercizio ISS 66-75 % del picco "
        "(122-139 bpm su 185) [P2]. Le attivita' con 'fuori' non sono errori: sono i punti da guardare insieme a Luca.",
        col_w=[0.08, 0.05, 0.15, 0.05, 0.05, 0.06, 0.05, 0.05, 0.06, 0.06, 0.34],
        intro="Ogni riga e' la media dei valori veri di un astronauta durante un tipo di attivita'. 'min' = minuti totali di quell'attivita' nel giorno; FC in bpm, SpO2 in %, FR in atti/min, HRV in ms, temperature in C.",
        cls="small")

    # ---- body state of the day (all NPCs)
    d = day["df"]
    h = hours(day)
    fig, axs = plt.subplots(2, 2, figsize=(11, 5.6))
    for n in NPCS:
        axs[0, 0].plot(h, d[f"{n}_core"], color=COL[n], lw=0.9, label=ALIAS[n])
        axs[0, 1].plot(h, d[f"{n}_dehyd"], color=COL[n], lw=0.9)
    axs[0, 0].set_title("Temperatura centrale (C)", fontsize=9)
    axs[0, 0].legend(fontsize=6, frameon=False, ncol=2)
    axs[0, 1].set_title("Acqua persa (% della massa corporea)", fontsize=9)
    night = (h >= 22) & (h <= 30)
    stage_y = d["cmd_stage"].values[night]
    axs[1, 0].step(h[night], stage_y, where="post", color=COL["cmd"], lw=0.9)
    axs[1, 0].set_yticks([0, 1, 2, 3, 5])
    axs[1, 0].set_yticklabels(["veglia", "N1", "N2", "N3", "REM"], fontsize=7)
    axs[1, 0].set_title("Fasi del sonno di ASTRO_01 (ora locale 22-6)", fontsize=9)
    win = (d["tod"] >= 14.0) & (d["tod"] < 14.05)
    axs[1, 1].plot(d["t"][win] - d["t"][win].iloc[0], d["cmd_rrint"][win], "o-", color=COL["cmd"], ms=2, lw=0.6, label="intervallo RR")
    axs[1, 1].plot(d["t"][win] - d["t"][win].iloc[0], 60000.0 / d["cmd_hr"][win], color="k", ls=":", lw=0.8, label="60000 / FC")
    axs[1, 1].legend(fontsize=6, frameon=False)
    axs[1, 1].set_title("Intervalli RR di ASTRO_01 a riposo (3 minuti alle 14:00)", fontsize=9)
    axs[1, 1].set_xlabel("secondi", fontsize=7)
    for ax in axs.flat:
        ax.tick_params(labelsize=7)
    fig.tight_layout()
    doc.fig(fig, "Stato del corpo nella giornata nominale",
            "In alto a sinistra: asse orizzontale = ora locale, asse verticale = temperatura centrale in C (minimo di notte, sale con l'esercizio delle 17). In alto a destra: acqua persa in % della massa corporea "
            "(cresce col sudore dell'allenamento e rientra bevendo). In basso a sinistra: fase del sonno di ASTRO_01 (asse verticale = codice della fase) dall'addormentamento alle 22 al risveglio. "
            "In basso a destra: asse orizzontale = secondi, asse verticale = millisecondi tra un battito e il successivo (punti) confrontato con 60000/FC (linea): in ritmo normale gli RR oscillano attorno a quel valore.",
            intro="Variabili che il modello tiene come stato (non solo come numeri imposti): temperatura centrale, acqua del corpo, sonno e intervalli tra battiti.")

    # ---- environment of the day
    fig, axes = plt.subplots(2, 3, figsize=(11, 5.4), sharex=True)
    h = hours(day)
    for ax, (c, t, lim) in zip(axes.flat, [("hab_ppCO2", "ppCO2 habitat (mmHg)", 3.0), ("hab_PIO2", "PIO2 habitat (mmHg)", 122),
                                           ("hab_T", "T habitat (C)", 27), ("hab_RH", "Umidita' habitat (%)", 75),
                                           ("hab_P", "Pressione habitat (mmHg)", None), ("eva_PIO2", "PIO2 modulo EVA (mmHg)", 122)]):
        ax.plot(h, day["df"][c], lw=0.8)
        if lim is not None:
            ax.axhline(lim, color="k", ls="--", lw=0.8)
        ax.set_title(t, fontsize=9)
        ax.tick_params(labelsize=7)
    fig.tight_layout()
    doc.fig(fig, "Ambiente nella giornata nominale",
            "Asse orizzontale: ora locale. Asse verticale: grandezza nel titolo (ppCO2 e PIO2 in mmHg, temperatura in C, umidita' in %, pressione in mmHg). Il tratteggio e' il limite NASA-STD-3001: superarlo fa scattare un allarme. "
            "Nell'ultimo pannello il modulo EVA e' vuoto per quasi tutto il giorno (la PIO2 resta a 127 mmHg).",
            intro="Aria dell'habitat e del modulo EVA durante la giornata normale: serve a verificare che l'ambiente resti dentro i limiti.")

    scen_rows = [[ev, EV_IT[ev][0], EV_IT[ev][1], EV_IT[ev][2], EV_IT[ev][3]] for ev in EVENTS]
    table_page(doc, "Scenari simulati", pd.DataFrame(scen_rows, columns=["Codice", "Situazione", "Quando", "Cosa succede", "Origine dei valori"]),
               "Ogni scenario simula la stessa giornata di routine; cambia solo l'evento. Lo stato 'nominal' / il nome dell'evento sono le etichette scritte nei dati per il modello di allerta.",
               col_w=[0.10, 0.15, 0.10, 0.34, 0.31], cls="small")

    # ---- events
    EVDEF = {
        "eva_nominal": ("med", ["hr", "spo2", "rr", "hrv"], [("eva", "P", None), ("eva", "PIO2", 122), ("eva", "ppCO2", 3.0)], (9.0, 11.5)),
        "eva_decompression": ("med", ["hr", "spo2", "state", "hrv"], [("eva", "P", None), ("eva", "PIO2", 122), ("eva", "ppCO2", 3.0)], (9.5, 11.5)),
        "eva_decompression_fatal": ("med", ["hr", "spo2", "state", "hrv"], [("eva", "P", None), ("eva", "PIO2", 122), ("eva", "ppCO2", 3.0)], (9.5, 11.5)),
        "fibrillation": ("eng", ["hr", "spo2", "rr", "hrv"], [], (10.0, 13.0)),
        "scrubber_failure": ("cmd", ["hr", "rr", "spo2", "hrv"], [("hab", "ppCO2", 3.0), ("hab", "T", 27)], (12.0, 26.0)),
        "co2_release": ("cmd", ["hr", "rr", "spo2", "hrv"], [("hab", "ppCO2", 3.0), ("hab", "PIO2", 122)], (12.0, 20.0)),
        "slow_leak": ("cmd", ["hr", "spo2", "rr", "hrv"], [("hab", "P", None), ("hab", "PIO2", 122), ("hab", "ppCO2", 3.0)], (12.0, 22.0)),
        "dehydration": ("bot", ["hr", "dehyd", "core", "hrv"], [], (6.0, 20.0)),
        "stress": ("cmd", ["hr", "hrv", "rr", "skin"], [], (8.0, 14.0)),
        "fever": ("cmd", ["hr", "core", "skin", "rr"], [], (7.0, 20.0)),
        "motion_sickness": ("bot", ["hr", "nausea", "hrv", "rr"], [], (7.0, 13.0)),
    }
    for ev in EVENTS:
        r = R[ev]
        npc, mets, envs, (x0, x1) = EVDEF[ev]
        h = hours(r)
        title_it, when, what, origin, check = EV_IT[ev]
        panels = [(f"{npc}_{k}", METRICS[k][0], None) for k in mets] + [(f"{m}_{k}", f"{m}: {k}", lim) for m, k, lim in envs]
        cols = 3 if len(panels) > 4 else 2
        rows_n = math.ceil(len(panels) / cols)
        fig, axs = plt.subplots(rows_n, cols, figsize=(11, 1.5 * rows_n + 0.3), squeeze=False)
        for ax in axs.flat:
            ax.set_visible(False)
        for i, (c, t, lim) in enumerate(panels):
            ax = axs.flat[i]
            ax.set_visible(True)
            ax.plot(h, r["df"][c], color=COL[npc] if c.startswith(npc) else "#1f77b4", lw=0.9)
            if lim is not None:
                ax.axhline(lim, color="k", ls="--", lw=0.7)
            if c.endswith("_state"):
                ax.set_ylim(-0.2, 4.2)
                ax.set_yticks([0, 1, 2, 3, 4])
            shade_faults(ax, r)
            ax.set_xlim(x0, min(x1, h[-1]))
            ax.set_title(t, fontsize=8)
            ax.tick_params(labelsize=6)
        fig.tight_layout()
        intro = (f'<p><b>Quando:</b> {esc(when)}. <b>Cosa succede:</b> {esc(what)}</p>'
                 f'<p><b>Origine dei valori:</b> {esc(origin)}</p>')
        after = table_html(event_table(r, npc, mets, ev), [0.28, 0.18, 0.18, 0.18, 0.18]) + event_notes(r, npc) + f'<p class="check">Da verificare: {esc(check)}</p>'
        doc.fig(fig, f"{title_it} - {NAME[npc]}",
                "Asse orizzontale: ora locale (h). Ogni pannello e' una grandezza (titolo con unita'); i primi sono i vitali dell'astronauta, gli ultimi l'aria del modulo (pressione e PIO2 in mmHg, ppCO2 in mmHg). "
                "L'area rosa e' il periodo in cui l'evento e' attivo, il tratteggio e' il limite NASA; 'Stato di salute' va da 0 (ok) a 4 (morto). La tabella sotto riporta la media nei 30 minuti prima dell'evento, "
                "il minimo e il massimo durante e la media nei 30 minuti dopo.",
                after=after, intro=intro, cls="ev")

    # ---- Luca declared vs model
    rows = []

    def win_mean(r, n, c, lo, hi):
        d_ = r["df"]
        sel = d_[(d_["tod"] >= lo) & (d_["tod"] < hi)] if "tod" in d_ else d_
        return sel[f"{n}_{c}"].mean()

    rows.append(["ASTRO_01 lavoro 7-12 h", "69.5 / 98.5", f"{win_mean(day, 'cmd', 'hr', 7, 12):.0f} / {win_mean(day, 'cmd', 'spo2', 7, 12):.1f}",
                 f"{win_mean(daym, 'cmd', 'hr', 7, 12):.0f} / {win_mean(daym, 'cmd', 'spo2', 7, 12):.1f}", "stazione: PIO2 149"])
    rows.append(["ASTRO_02 T2 17:00-17:45", "142.5 / 96.2", f"{win_mean(day, 'bot', 'hr', 17.1, 17.75):.0f} / {win_mean(day, 'bot', 'spo2', 17.1, 17.75):.1f}",
                 f"{win_mean(daym, 'bot', 'hr', 17.1, 17.75):.0f} / {win_mean(daym, 'bot', 'spo2', 17.1, 17.75):.1f}", "MET 7.0 (con il VO2max di Luca la FC resta sotto il brief: da rivedere)"])
    rows.append(["ASTRO_03 fibrillazione", "150 / 93", f"{fib_w['eng_hr'].mean():.0f} / {fib_w['eng_spo2'].mean():.1f}", "-", "imposto da Luca (hr_to, spo2_to)"])
    rows.append(["ASTRO_04 EVA nominale", "132.5 / 94", f"{eva_hr:.0f} / {eva_sp:.1f}", "-", f"PIO2 EVA {eva_pio2:.0f} mmHg"])
    rows.append(["ASTRO_04 EVA emergenza", "172 / 88", f"{dec_hr_max:.0f} (max) / {dec_sp_min:.0f} (min)", "-", f"PIO2 {dec_pio2:.1f}: incosciente dopo {dec_loc:.0f} s"])
    table_page(doc, "Valori di Luca (FC / SpO2) contro il modello",
               pd.DataFrame(rows, columns=["Situazione", "Luca FC / SpO2", "Modello: stazione 758 mmHg (adottata)", "Modello: habitat Marte (confronto)", "Nota"]),
               "Dove la differenza e' grande il modello segue le fonti [P1][P2]; non significa che il modello abbia ragione: serve la decisione di Luca "
               "(vedi incongruenze 2, 3 e domanda 1). SpO2 in decompressione: valore minimo; FC: massimo.", col_w=[0.20, 0.14, 0.18, 0.18, 0.30],
               intro="Valori attesi indicati nel brief a confronto con quanto produce la simulazione nelle stesse situazioni (FC in bpm / SpO2 in %).")

    text_page(doc, "Incongruenze nel brief ricevuto", incong)
    table_page(doc, "Monitor atmosfera di Luca applicato alla simulazione (1 campione al minuto)",
               pd.DataFrame(atm_rows, columns=["Atmosfera simulata", "Luogo", "Minuti occupati", "ppO2 = P x %O2 (mmHg)", "Esito della funzione"]),
               "La funzione di Luca segnala 'CRITICAL ipossia' quando ppO2 (pressione totale x frazione di O2) e' sotto 148 mmHg o l'O2 e' sotto 19.5 %: soglie da livello del mare (758 mmHg x 19.5 % = 148). "
               "Con l'atmosfera della stazione (758 x 21 % = 159) non scatta; con la tuta (350 mmHg x 42 % = 147) e con l'habitat marziano (527 x 26.5 % = 140) scatta anche in condizioni nominali. NASA usa invece la PIO2 (che sottrae 47 mmHg di vapore acqueo) con limite 122-127 mmHg. "
               "Inoltre il limite di O2 alto (23.5 %, rischio incendio) e' pensato per una cabina: in una tuta, per sua natura, l'O2 e' piu' alto (28 % nel brief, 42 % nella nostra assunzione) e la funzione segnala sempre allarme. Serve decidere quali criteri valgono per la tuta (domande 2 e 6).",
               col_w=[0.26, 0.10, 0.10, 0.16, 0.38])

    sub = []
    for lbl, r in (("EVA nominale", ev_nom), ("EVA decompressione", ev_dec)):
        d_ = r["df"][r["df"]["med_mod"] == "eva"]
        alt_i = d_["eva_P"].map(isa_altitude_m)
        alt_e = d_["eva_PIO2"].map(pio2_equiv_altitude_m)
        st = alt_e.map(monitor_analysis).value_counts()
        o2m = alt_e.map(lambda a: o2_minimum(a * 3.28084 if np.isfinite(a) else 1e9)).max()
        sub.append([lbl, f"{alt_i.median():,.0f}", f"{alt_e.replace(np.inf, np.nan).median():,.0f}",
                    ", ".join(f"{k}: {v}s" for k, v in st.items()), f"{o2m} % / {d_['eva_o2pct'].median():.0f} %"])
    table_page(doc, "Regole di Luca applicate ai valori simulati dell'EVA",
               pd.DataFrame(sub, columns=["Scenario", "Alt. da pressione (m)", "Alt. equiv. PIO2 (m)", "Stato ipossia (secondi)", "O2 min richiesto / attuale"]),
               "Alt. da pressione = atmosfera standard ISA invertita; alt. equiv. PIO2 = quota in aria con la stessa PIO2 (piu' fisiologica). 'inf' = nessun O2 inspirato.",
               col_w=[0.15, 0.15, 0.15, 0.35, 0.20])
    csv_tab = {1000: ("NOMINALE", 21), 3000: ("PRE-ALLERTA", 27), 5500: ("PERICOLO AVANZATO", 44), 7000: ("CRITICO ELEVATO", 78),
               12000: ("EMERGENZA SPAZIALE", 100)}
    cmp_rows = [[hh, monitor_analysis(hh), o2_minimum(hh * 3.28084), st_, o2_, f"{isa_mmhg(hh):.0f}"] for hh, (st_, o2_) in csv_tab.items()]
    table_page(doc, "Due tabelle di soglie in conflitto: notebook vs monitor_parametri_spaziali.csv",
               pd.DataFrame(cmp_rows, columns=["Quota (m)", "Stato (notebook)", "O2 min % (notebook)", "Stato (CSV)", "O2 min % (CSV)", "Pressione ISA (mmHg)"]),
               "Stato ipossia e O2 minimo differiscono tra le due fonti di Luca. Va deciso quale vale.")

    # ---- ECG
    fig, axes = plt.subplots(3, 2, figsize=(11, 6.2))
    picks = [("ASTRO_01", 1.0), ("ASTRO_02", 1.0), ("ASTRO_03 (fibrillazione)", 0.0), ("ASTRO_04 EVA nominale", 1.0),
             ("ASTRO_04 EVA emergenza", 0.0)]
    for ax, (k, label) in zip(axes.flat, picks):
        idx = ecg_row(label)
        ax.plot(ecg[idx, :-1], color="#1f77b4" if label == 1.0 else "#d62728", lw=1)
        ax.set_title(f"{k}: riga {idx}, label {label}", fontsize=9)
        ax.tick_params(labelsize=7)
    axes.flat[-1].axis("off")
    axes.flat[-1].text(0, 0.5, f"ecg_dataset_megatron.csv: {len(ecg)} righe x 140 campioni (60 label 1.0, 40 label 0.0)\n"
                       f"valori da {ecg[:, :-1].min():.2f} a {ecg[:, :-1].max():.2f}. Riga fissa per NPC (seed 42),\n"
                       "non generata dai vitali: l'etichetta va legata all'evento.", fontsize=8)
    fig.tight_layout()
    doc.fig(fig, "ECG assegnati agli NPC",
            "Asse orizzontale: campione del battito (140 per riga). Asse verticale: ampiezza normalizzata del segnale. Blu = battito normale (label 1.0), rosso = anomalo (label 0.0).",
            intro="Ogni astronauta riceve una riga del dataset ECG di Luca; la riga non e' generata dai vitali simulati.")

    # ---- SpO2 curve
    fig, ax = plt.subplots(figsize=(11, 4.8))
    xs, ys = zip(*SPO2_VS_PIO2)
    ax.plot(xs, ys, "o-", color="#1f77b4")
    for label, x in (("habitat Marte 127", 127), ("sup. nominale 85 (EVA Luca)", 85), ("limite NASA 122", 122), ("ISS 149", 149)):
        ax.axvline(x, color="#999", ls=":", lw=0.8)
        ax.text(x, 12, label, rotation=90, fontsize=7, va="bottom")
    ax.set_xlabel("PIO2 (mmHg)")
    ax.set_ylabel("SpO2 stazionaria (%)")
    fig.tight_layout()
    doc.fig(fig, "Curva SpO2 contro PIO2 usata dal modello",
            "Asse orizzontale: PIO2 = pressione parziale dell'ossigeno inspirato (mmHg) = (pressione totale - 47) x frazione di O2. Asse verticale: SpO2 stazionaria (%). "
            "Le linee verticali sono i valori incontrati nelle simulazioni: 85 = EVA con 28 % O2 (brief), 122 = limite NASA, 127 = EVA assunta e habitat Marte, 149 = aria della stazione (adottata). Sotto 70 mmHg i punti sono ESTIMATE.",
            intro="Relazione tra ossigeno inspirato e saturazione del sangue: determina la SpO2 in ogni ambiente simulato [P1].")

    text_page(doc, "Domande per Luca", questions)
    table_page(doc, "Fonti", sources, "Ricerca online del 2026-11-14. Elenco con URL completi: docs/reference/physiology-sources.md.",
               col_w=[0.04, 0.30, 0.30, 0.31, 0.05], cls="small")

    html_path = doc.write()
    ok = to_pdf(html_path, OUT / "report.pdf")
    print(f"report: {OUT / 'report.pdf' if ok else html_path}")


if __name__ == "__main__":
    main()
