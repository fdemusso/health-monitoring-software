"""Verification PDF for the bioengineer: what each NPC produces in a normal day and in every event scenario.

    uv sync --extra dev --extra report
    uv run python tools/npc_report.py              # runs every scenario (~5 min), writes output/npc_report/report.pdf
    uv run python tools/npc_report.py --reuse      # re-plots from the cached runs

Scenarios: scenarios/nominal.yaml (baseline day), scenarios/events/*.yaml. Luca's rule functions are copied from
notebooks/luca/Critical_condition_monitor.ipynb and applied to the simulated EVA values.
"""

from __future__ import annotations

import argparse
import math
import pickle
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from ares3.core.engine import Engine
from ares3.plugins.physiology.baseline import SPO2_VS_PIO2, spo2_from_pio2
from ares3.schemas.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "npc_report"
MMHG = 7.50062
NPCS = ["cmd", "bot", "eng", "med"]  # = ASTRO_01, 02, 03, 04
ALIAS = {"cmd": "ASTRO_01", "bot": "ASTRO_02", "eng": "ASTRO_03", "med": "ASTRO_04"}
NAME = {n: f"{ALIAS[n]} ({n})" for n in NPCS}
COL = {"cmd": "#1b9e77", "bot": "#d95f02", "eng": "#7570b3", "med": "#e7298a"}
ACT_COL = {"sleep": "#4c72b0", "meal": "#ccb974", "nominal": "#8c8c8c", "work": "#8c8c8c", "rest": "#b0b0b0",
           "exercise_aerobic": "#d62728", "exercise_resistive": "#ff7f0e", "recovery": "#2ca02c"}
METRICS = {"hr": ("FC (bpm)", "hr"), "spo2": ("SpO2 (%)", "spo2"), "rr": ("Resp. (atti/min)", "resp_rate"),
           "hrv": ("HRV (ms)", "hrv_rmssd"), "skin": ("T cutanea (C)", "skin_temp_c")}
EVENTS = ["eva_nominal", "eva_decompression", "fibrillation", "scrubber_failure", "co2_release", "slow_leak",
          "dehydration", "stress", "fever", "motion_sickness"]
# Luca's brief: values he expects per astronaut (midpoint of his ranges)
LUCA = {"cmd": dict(hr=69.5, spo2=98.5, o2=21.0, co2=0.25, p=758.0), "bot": dict(hr=142.5, spo2=96.2, o2=20.8, co2=0.38, p=758.0),
        "eng": dict(hr=150.0, spo2=93.0, o2=20.8, co2=0.38, p=758.0), "med": dict(hr=132.5, spo2=94.0, o2=28.0, co2=0.15, p=350.0)}
LUCA_EMERG = dict(hr=172.0, spo2=88.0, o2=20.0, p=50.0, alt_m=7000)



# event -> (titolo, quando, cosa simula, da dove vengono i valori, cosa verificare)
EV_IT = {
    "eva_nominal": ("Uscita EVA senza problemi", "ASTRO_04, 10:00-10:30", "Passeggiata esterna di 30 minuti, supporto vitale della tuta attivo.",
                    "Atmosfera tuta: 350 mmHg, 42 % O2 (nostra assunzione, vedi pagina Ambiente); sforzo 5.5 MET (ESTIMATE).",
                    "FC attorno a 125 bpm (la media NASA delle EVA e' 131-135) e SpO2 ~96 %: sono plausibili per una EVA? Nessun allarme atteso."),
    "eva_decompression": ("Decompressione esplosiva durante la EVA", "ASTRO_04, evento alle 10:10", "In un solo istante la pressione passa da 350 a 50 mmHg, il supporto vitale si spegne.",
                          "Evento e valori di pressione dal brief di Luca; i vitali NON sono imposti (Luca: FC 172, SpO2 88): seguono l'ambiente.",
                          "Cosa deve produrre l'NPC quando la pressione parziale di ossigeno va a ~0? Il modello fa crollare la SpO2 e sale la FC; la perdita di coscienza non e' modellata."),
    "fibrillation": ("Possibile fibrillazione atriale", "ASTRO_03, 11:10-11:25", "Per 15 minuti la FC sale a 150 bpm e la SpO2 scende a 93 % mentre lavora in habitat.",
                     "FC 150 e SpO2 93 dal brief di Luca; HRV x2 e respirazione +3/min sono ESTIMATE (in AF l'RMSSD tende ad aumentare).",
                     "Il quadro FC 150 / SpO2 93 e' coerente con la fibrillazione che ha in mente? L'HRV e la respirazione vanno corrette?"),
    "scrubber_failure": ("Guasto del depuratore di CO2", "habitat, 13:00-23:00", "Il depuratore di CO2 dell'habitat si ferma per 10 ore; l'equipaggio continua a produrre CO2.",
                         "Evento fisico; effetto di CO2 su FC/respirazione: ESTIMATE (+1 bpm e +1.5 resp/min per mmHg sopra 2).",
                         "La CO2 sale fino al limite NASA (3 mmHg) e fa scattare l'allarme: l'effetto sui vitali (piccolo) e' realistico?"),
    "co2_release": ("Rilascio improvviso di CO2", "habitat, 13:00-15:00", "Una sorgente di CO2 supera la capacita' del depuratore per 2 ore.",
                    "Evento fisico; stessa risposta dei vitali alla CO2 (ESTIMATE).",
                    "Come per il guasto del depuratore, con salita piu' rapida: confrontare tempi e soglie."),
    "slow_leak": ("Perdita lenta di pressione", "habitat, 13:00-19:00", "L'habitat perde lo 0.001 % di gas al secondo (~20 % in 6 ore); il regolatore compensa solo in parte.",
                  "Evento fisico; SpO2 dalla curva PIO2 [P1] (valida solo per ipossia marcata).",
                  "La pressione scende fino a toccare il limite NASA di ossigeno (122 mmHg)? I vitali dovrebbero reagire prima?"),
    "dehydration": ("Disidratazione progressiva", "ASTRO_02, 07:00-15:00", "Nel corso di 8 ore la FC sale di ~12 bpm a riposo e la HRV scende del 15 %.",
                    "Tutti i valori sono ESTIMATE (nessuna fonte quantitativa trovata).",
                    "Entita' e velocita' dell'effetto: sono ragionevoli? Quali altri vitali cambiano (temperatura cutanea)?"),
    "stress": ("Stress acuto", "ASTRO_01, 10:00-12:00", "FC +10 bpm, respirazione +2/min, HRV ridotta del 40 % per 2 ore.",
               "Valori ESTIMATE.", "Valori e durata ragionevoli per uno stress acuto in missione?"),
    "fever": ("Febbre", "ASTRO_04, 11:00-17:00", "Febbre di +1.5 C per 6 ore: FC +13 bpm, respirazione +3/min, temperatura cutanea +1 C.",
              "FC da letteratura (8.5 bpm per grado C) [P8]; resto ESTIMATE.",
              "La temperatura cutanea (misurata al polso) sale quanto la febbre? Come cambiano respirazione e HRV?"),
    "motion_sickness": ("Mal di spazio (nausea)", "ASTRO_02, 08:00-09:00", "Un'ora di nausea: FC +10 bpm, respirazione +2/min, HRV -20 %.",
                        "Valori ESTIMATE; fenomeno tipico delle prime ore-giorni in microgravita'.",
                        "Tipico dei primi giorni in microgravita': l'intensita' e la durata sono ragionevoli?"),
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
            "name": sc.file.name}


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


def text_page(pdf, title: str, blocks: list[str], size: float = 8.4, wrap: int = 125) -> None:
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.04, 0.96, title, fontsize=15, weight="bold", va="top")
    y = 0.915
    for b in blocks:
        bold = b.startswith("##")
        txt = b.lstrip("# ").strip()
        for ln in textwrap.wrap(txt, 95 if bold else wrap) or [""]:
            if y < 0.03:  # overflow: continue on a new page
                pdf.savefig(fig)
                plt.close(fig)
                fig = plt.figure(figsize=(11.69, 8.27))
                y = 0.96
            fig.text(0.04, y, ln, fontsize=size + (1.5 if bold else 0), weight="bold" if bold else "normal", va="top")
            y -= 0.021 if not bold else 0.03
        y -= 0.008
    pdf.savefig(fig)
    plt.close(fig)


def table_page(pdf, title: str, df: pd.DataFrame, note: str = "", col_w=None, font: float = 7.5, scale: float = 1.6) -> None:
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.04, 0.96, title, fontsize=14, weight="bold", va="top")
    ax = fig.add_axes([0.03, 0.14, 0.94, 0.78])
    ax.axis("off")
    ncol = len(df.columns)
    widths = col_w or [1.0 / ncol] * ncol
    # wrap every cell to its column width (about 18 chars per inch at 8 pt) and grow the row to fit
    chars = [max(8, int(w * 11.0 * 18 * 8.0 / font * 0.78)) for w in widths]
    cells = [["\n".join(textwrap.wrap(str(v), chars[j])) or "" for j, v in enumerate(row)] for row in df.values]
    heads = ["\n".join(textwrap.wrap(str(c), chars[j])) for j, c in enumerate(df.columns)]
    tb = ax.table(cellText=cells, colLabels=heads, loc="upper center", cellLoc="left", colWidths=widths)
    tb.auto_set_font_size(False)
    tb.set_fontsize(font)
    tb.scale(1, 1.0)
    base = 0.022 * font / 7.5 * 1.15
    for r in range(len(cells) + 1):
        lines = max(c.count("\n") + 1 for c in ([heads] + cells)[r])
        for j in range(ncol):
            cell = tb[r, j]
            cell.set_height(base * lines + 0.012)
            if r == 0:
                cell.set_facecolor("#dde3ea")
                cell.set_text_props(weight="bold")
    if note:
        fig.text(0.04, 0.11, "\n".join(textwrap.wrap(note, 190)), fontsize=8, va="top")
    pdf.savefig(fig)
    plt.close(fig)


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


def caption(fig, text: str, y: float = 0.012) -> None:
    fig.text(0.02, y, "\n".join(textwrap.wrap(text, 190)), fontsize=6.8, va="bottom", color="#333")


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
    after = dec[(dec["t"] > 4260) & (dec["med_mod"] == "eva")]
    dec_sp_min, dec_hr_max, dec_pio2 = after["med_spo2"].min(), after["med_hr"].max(), after["eva_PIO2"].mean()
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
        "Questo documento mostra quali dati producono i 4 astronauti simulati (NPC) in una giornata normale e in 10 situazioni particolari "
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
        "ASTRO_01 comandante (uomo, 76 kg), ASTRO_02 botanica (donna, 61.5 kg, si allena sul tapis roulant T2), ASTRO_03 ingegnera (donna, 84 kg, "
        "episodio di fibrillazione), ASTRO_04 medico (donna, 65 kg, uscita EVA). Pesi e sesso sono quelli del brief di Luca.",
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
         "NON simulata: nessuna fase di lancio", "Domanda 11"],
        ["ENERGY_INTAKE, cella 2: stazione 'statica'", "Stazione, lavoro o riposo", "heart_rate, peso_kg, durata, allarme ECG, score",
         "FC, peso disponibili; MAE dipende dal modello ECG", "Metabolismo basale -10 % in microgravita' (nel nostro modello non applicato)"],
        ["ENERGY_INTAKE, cella 3: allenamento ISS", "Stazione, esercizio con T2, ARED o CEVIS", "heart_rate, peso_kg, durata, macchinario, allarme ECG, score",
         "Macchinario non ancora nei dati", "Usiamo T2 per l'aerobico di ASTRO_02, ARED per la forza (ipotesi)"],
        ["ENERGY_INTAKE, cella 4: EVA / rover", "EVA", "heart_rate, peso_kg, durata, oxygen_perc (= SpO2), allarme ECG, score",
         "FC, SpO2 disponibili", "SpO2 < 95 % / < 90 % aumenta il costo energetico del 15 % / 30 %"],
        ["ENERGY_INTAKE, cella 5: reintegrazione", "STATION oppure OUTSIDE", "scenario, durata, heart_rate, peso, sex, kcal e acqua giornaliere",
         "scenario e sex disponibili; kcal e acqua giornaliere NO", "Serve un consumo di cibo e acqua simulato"],
        ["stress-level-detection", "Non specificata", "colonne di Stress-lysis.csv (es. passi)", "Non simulabile: file non fornito", "Domanda 10"],
    ], columns=["Sezione dei dati di Luca", "Fase di missione", "Ingressi", "Disponibile dalla simulazione?", "Nota"])

    limits = pd.DataFrame([
        ["PIO2 - ossigeno inspirato", "media su 1 h >= 127 mmHg; mai sotto 122 mmHg; sopra 356 = avviso", "Pressione parziale dell'O2 nell'aria inspirata = (pressione totale - 47 mmHg di vapore acqueo) x frazione di O2. Determina quanto O2 arriva al sangue.", "Sotto il limite l'ossigenazione cala (SpO2)"],
        ["ppCO2 - anidride carbonica", "media su 1 h <= 3 mmHg", "Pressione parziale della CO2 nell'aria (0.4 % a 758 mmHg). Nello spazio i sintomi compaiono gia' a 3.5 mmHg.", "Mal di testa, respiro piu' frequente"],
        ["Pressione totale", "tra 34.5 e 103 kPa (259-772 mmHg)", "Pressione dell'aria del modulo.", "Troppo bassa o troppo alta e' pericoloso"],
        ["Temperatura", "tra 18 e 27 C", "Temperatura dell'aria.", "Comfort e termoregolazione"],
        ["Umidita' relativa", "tra 25 e 75 %", "Vapore acqueo rispetto alla saturazione.", "Comfort, condensa"],
    ], columns=["Grandezza", "Limite NASA-STD-3001", "Cosa significa", "Perche' conta"])

    variables = pd.DataFrame([
        ["FC (hr)", "bpm", "Battiti al minuto", "Riposo + sforzo (MET) + ambiente + fase (sonno); ritardo 40 s salita, 65 s discesa", f"{ranges['hr'][0]:.0f} - {ranges['hr'][1]:.0f}"],
        ["SpO2 (spo2)", "%", "Saturazione di ossigeno nel sangue", "Curva dalla PIO2 [P1]; scostamenti degli episodi", f"{ranges['spo2'][0]:.1f} - {ranges['spo2'][1]:.1f}"],
        ["Freq. respiratoria (resp_rate)", "atti/min", "Respiri al minuto", "14 a riposo (12 nel sonno) + 1.5 per MET + CO2", f"{ranges['rr'][0]:.0f} - {ranges['rr'][1]:.0f}"],
        ["HRV (hrv_rmssd)", "ms", "Variabilita' del battito (RMSSD)", "45 ms a riposo, scende con la FC, +-10 % nel giorno", f"{ranges['hrv'][0]:.0f} - {ranges['hrv'][1]:.0f}"],
        ["Temperatura cutanea (skin_temp_c)", "C", "Temperatura della pelle (polso)", "33.5 + 0.05 per MET + sonno + ambiente", f"{ranges['skin'][0]:.1f} - {ranges['skin'][1]:.1f}"],
        ["MET", "-", "Intensita' dell'attivita' (1 = riposo)", "Dalla routine: sonno 0.9, lavoro 1.45, esercizio 7, EVA 5.5", "0.9 - 7"],
        ["Attivita' e modulo", "-", "Cosa fa e dove si trova", "Dalla routine giornaliera", "-"],
        ["PIO2, ppCO2, P, T, UR del modulo", "mmHg, mmHg, mmHg, C, %", "Aria del modulo in cui si trova", "Fisica dei gas: respirazione degli astronauti, impianti, guasti", f"hab: PIO2 {dd['hab_PIO2'].min():.0f}-{dd['hab_PIO2'].max():.0f}, ppCO2 {dd['hab_ppCO2'].min():.1f}-{dd['hab_ppCO2'].max():.1f}"],
        ["Misura dei sensori", "come sopra", "Valore letto dal sensore", "Valore vero + rumore + ritardo; i guasti dei sensori non sono simulati in questi scenari", "-"],
        ["Etichetta anomalia (is_anomaly, anomaly_type)", "-", "Vale 'fault attivo' per ogni riga di dati", "Dall'evento attivo; fuori dagli eventi = 'nominal'", "-"],
    ], columns=["Variabile", "Unita'", "Cosa rappresenta", "Come viene prodotta", "Intervallo nel giorno normale"])

    model_text = [
        "## Come nascono i vitali",
        "Ogni astronauta ha un valore di riferimento a riposo. Su quello si sommano tre effetti: lo sforzo (piu' MET, piu' FC e respiro), l'ambiente (poco ossigeno = SpO2 piu' bassa e FC piu' alta; "
        "CO2 alta = respiro piu' frequente) e la fase della giornata (nel sonno FC -20 %, HRV piu' alta, pelle piu' calda). Il valore vero si avvicina al valore obiettivo con ritardo: la FC sale con costante di "
        "tempo ~40 s e scende in ~65 s. Gli episodi (febbre, fibrillazione, stress...) aggiungono uno scostamento che entra in alcuni minuti e rientra gradualmente (30 s) quando l'evento finisce.",
        "## Cosa il modello non fa",
        "Non simula: perdita di coscienza, calo di SpO2 da sforzo, aritmia battito per battito, variazioni circadiane della FC, differenze per sesso/eta' nei valori di riposo, adattamento alla microgravita'. "
        "Gli stessi valori di riposo sono usati per tutti (tranne il comandante, FC 64).",
    ]

    incong = [
        "## Incongruenze nel brief ricevuto",
        "Per ciascuna: cosa dice il brief, cosa risulta dai calcoli e perche' conta. Le domande corrispondenti sono nell'ultima sezione.",
        f"1) Altitudine e pressione. Il brief associa 350 mmHg a 3000 m e 50 mmHg a 7000 m. In atmosfera standard 350 mmHg corrispondono a ~{alt_p350:,.0f} m e 50 mmHg a ~{alt_p50 / 1000:,.0f} km. "
        "Nel notebook l'altitudine e' l'altitudine equivalente della tuta (o la quota del decollo) e guida le regole di ipossia e di O2 minimo: con 3000 m l'esito e' 'condizioni stabili', con la quota che la pressione implica sarebbe 'pericolo'.",
        f"2) Ossigeno della tuta. 350 mmHg e 28 % O2 danno PIO2 {pio2_luca_eva:.0f} mmHg (limite NASA 122) e, secondo la curva di letteratura [P1], SpO2 ~{spo2_luca_eva:.0f} %; il brief indica SpO2 94 %. "
        "Una tuta reale usa 222 mmHg con O2 100 % (PIO2 ~175 mmHg) [P11]; la proposta NASA per Marte e' 8.2 psia (424 mmHg) con 34 % O2 (PIO2 128 mmHg, non validata). Abbiamo assunto il 42 % (PIO2 127).",
        f"3) Emergenza EVA. A 50 mmHg e 20 % O2 la PIO2 e' ~{pio2(50, 20):.1f} mmHg, praticamente vuoto. Il brief stesso indica perdita di coscienza in 9-15 s; la letteratura [P1] riporta 0-15 s a PIO2 28 mmHg dopo decompressione rapida. "
        f"FC 172 e SpO2 88 % descrivono invece una persona ancora cosciente. Nel modello la SpO2 scende a {dec_sp_min:.0f} % (minimo del modello) e la FC a {dec_hr_max:.0f} bpm.",
        f"4) Passo temporale. La caduta 350->50 mmHg in 0.2 s avviene in un solo passo di simulazione (1 s). Applicando la regola barotrauma ai dati simulati il risultato e' '{baro_sim}', con i valori del brief (0.2 s) e' '{baro_luca}'. "
        "Per rilevare l'esplosiva servono passi <= 0.1 s attorno all'evento o un campo che dichiari la durata.",
        "5) Atmosfera della stanza. ASTRO_02 e ASTRO_03 sono indicati con 20.8 % O2 e 0.38 % CO2, ASTRO_01 con 21.0 % e 0.25 %, tutti nella stessa stanza (3 astronauti, 60 m3). Nello stesso volume e nello stesso istante l'aria e' una sola. "
        f"0.38 % di CO2 a 758 mmHg e' ~2.9 mmHg, a ridosso del limite NASA di 3 mmHg. Nella simulazione la CO2 dell'habitat non supera {dd['hab_co2pct'].max():.2f} %.",
        "6) Dati anagrafici. ASTRO_02 e' descritto 'uomo' ma ha sex F e 61.5 kg. Il blocco 'astro_4' compare due volte (il terzo e' ASTRO_03). Per ASTRO_02/03 'oxygenperc' e' 21 ma 'o2_perc_attuale' e' 20.8.",
        "7) Due tabelle di soglie. La funzione del notebook e il file monitor_parametri_spaziali.csv danno stati di ipossia e O2 minimo diversi alla stessa quota (pagina dedicata).",
        f"8) Fibrillazione. FC 150 e SpO2 93 % a riposo sono simili a un allenamento intenso (ASTRO_02: {bot_ex:.0f} bpm): su FC e SpO2 i due casi non si separano, serve l'ECG (label 0.0) e il contesto 'in_allenamento'. "
        "Nella fibrillazione l'HRV (RMSSD) tende ad aumentare [P9]: il modello lo raddoppia (ESTIMATE).",
        f"9) Intensita' dell'allenamento. Il catalogo di attivita' assegna 9.7 MET all'esercizio aerobico (FC ~180, 97 % del massimo); NASA riporta sessioni sul tapis roulant ISS al 66-75 % del picco di FC [P2]. Abbiamo usato 7.0 MET: FC media {bot_ex:.0f} bpm (brief: 142.5), circa 78 % del massimo.",
        "10) ECG. Il dataset ha 100 righe da 140 campioni (60 normali = label 1.0, 40 anomale = label 0.0). Ogni NPC riceve una riga fissa; l'ECG non viene generato dai vitali. L'etichetta andrebbe legata all'evento (0.0 durante fibrillazione ed emergenza).",
    ]

    questions = [
        "## Decisioni gia' prese (se non corrette da Luca)",
        "Gli NPC sono ASTRO_01 comandante, ASTRO_02 botanica, ASTRO_03 ingegnera, ASTRO_04 medico (confermato). L'ambiente e' la stazione (758 mmHg, 21 % O2). Per l'EVA usiamo 350 mmHg con 42 % di ossigeno invece di 28 %, perche' il valore del brief da' PIO2 sotto il limite NASA. "
        "L'esercizio aerobico e' fissato a 7.0 MET e la EVA a 5.5 MET.",
        "## 1) Ambiente di riferimento: conferma stazione/livello del mare",
        "Contesto: abbiamo adottato l'ambiente dei suoi profili 'STATION' (758 mmHg, 21 % O2, microgravita'): e' coerente con altitudine 0, soglia ppO2 148 mmHg, macchinari ISS e metabolismo in microgravita'. "
        f"L'habitat marziano (70.3 kPa, 26.5 % O2) darebbe PIO2 127 mmHg e SpO2 a riposo ~{spo2_mars:.0f} %, contro ~{spo2_station:.0f} % della stazione. Ci serve: conferma che il modello di allerta lavora in ambiente ISS/livello del mare "
        "(e se mai servira' anche Marte, con quali soglie).",
        "## 2) Atmosfera e volume della tuta EVA",
        "Contesto: vedi incongruenza 2. Opzioni: 350 mmHg al 28 % (brief, PIO2 85, SpO2 attesa ~83 %), 350 mmHg al 42 % (nostra assunzione, PIO2 127), tuta EMU 222 mmHg con O2 100 %, tuta marziana 424 mmHg con 34 %. "
        "Il volume di 12 m3 e' un airlock/rover o una tuta (0.1-0.2 m3)? Ci serve: i valori reali che intende usare.",
        "## 3) Cosa deve produrre l'NPC durante l'emergenza EVA",
        f"Contesto: a 50 mmHg la PIO2 e' ~{pio2(50, 20):.1f} mmHg. Il modello porta la SpO2 a {dec_sp_min:.0f} % (limite inferiore del modello) e la FC a {dec_hr_max:.0f} bpm, non simula la perdita di coscienza. Il brief indica FC 172 e SpO2 88 %. "
        "Ci serve: sono i valori iniziali dopo la rottura (da cui l'NPC peggiora) oppure a regime? Vuole un segnale di perdita di coscienza dopo 9-15 s?",
        "## 4) Altitudine",
        "Contesto: incongruenza 1. Assunzione attuale: l'altitudine non viene calcolata. Ci serve: quale grandezza considera 'vera' (pressione, PIO2 o altitudine) per le sue regole; proponiamo di derivare l'altitudine equivalente dalla PIO2.",
        "## 5) Quale tabella di soglie vale",
        "Contesto: incongruenza 7. Ci serve: la tabella corretta per stati di ipossia e O2 minimo richiesto.",
        "## 6) Significato di tempo_trascorso_secondi e criteri del monitor atmosfera",
        "Contesto: dal notebook, num_astronauti e' il numero di persone nel modulo e tempo_trascorso_secondi e' l'intervallo tra pressione iniziale e attuale (1.0 normale, 0.2 emergenza). "
        "La funzione di atmosfera allarma con ppO2 = P x %O2 sotto 148 mmHg (soglia da livello del mare). Con la stazione (758 x 21 % = 159) non scatta; con la tuta (350 x 42 % = 147) e con l'habitat marziano (140) scatta anche in condizioni normali. "
        "Il limite O2 > 23.5 % (rischio incendio) vale per una cabina ma scatta sempre in tuta (O2 28-42 %). Ci serve: conferma del significato di tempo_trascorso_secondi e quali criteri usare per l'ossigeno in cabina e in tuta (ppO2 oppure PIO2 con limite NASA 122-127 mmHg; limite di O2 alto solo per la cabina).",
        "## 7) Fibrillazione: valori clinici",
        "Contesto: FC 150 e SpO2 93 % sono nel brief; HRV x2 e respirazione +3 sono nostre stime. Ci serve: i valori clinici che considera corretti per FC, SpO2, HRV e respirazione, e come la SpO2 misurata al polso viene disturbata dall'aritmia.",
        "## 8) Valori a riposo",
        "Contesto: usiamo FC 65 (comandante 64), SpO2 98, respirazione 14, HRV 45 ms per tutti. Ci serve: valori per persona (sesso, eta', forma fisica) e se desidera una variazione circadiana.",
        "## 9) Disidratazione, stress, nausea, febbre",
        "Contesto: nessuna fonte quantitativa per disidratazione, stress e nausea (per la febbre: +8.5 bpm per grado C). Ci serve: intervalli di FC, HRV, respirazione e temperatura per ciascun evento e la loro durata tipica.",
        "## 10) Ingressi del modello di allerta",
        "Contesto: il simulatore produce FC, SpO2, respirazione, HRV, temperatura cutanea, ECG (riga del dataset) e ambiente, a 1 campione al secondo. I suoi moduli (pagina 'Dati che i moduli di Luca si aspettano') usano FC, SpO2, peso, sesso, macchinario, luogo, atmosfera e punteggio ECG, ma non respirazione, HRV e temperatura cutanea. "
        "Il modulo di stress usa un file (Stress-lysis.csv) che non abbiamo. Ci serve: il csv dello stress con le sue variabili (es. passi), e conferma che respirazione, HRV e temperatura cutanea non servono (altrimenti con quale ruolo). "
        "Il macchinario (T2/ARED/CEVIS) va aggiunto ai dati: usiamo T2 per l'esercizio aerobico di ASTRO_02 e ARED per quello di forza.",
        "## 11) Decollo dalla Terra",
        "Contesto: i notebook considerano il decollo (calcolo energetico con forze G, miscela di ossigeno durante il decollo, strati atmosferici). La simulazione non ha questa fase. "
        "Ci serve: vuole uno scenario di decollo? In tal caso servono profilo di quota e di accelerazione nel tempo, pressione e miscela della tuta, durata e vitali attesi (FC > 140 nel suo calcolo energetico).",
        "## 12) Dati del brief da correggere",
        "ASTRO_02 e' uomo o donna? I blocchi astro_4 sono due? Qual e' il valore corretto di ossigeno per ASTRO_02/03 (20.8 o 21)?",
    ]

    sources = pd.DataFrame([
        ["P1", "Curva SpO2 contro PIO2 e tempo di coscienza utile", "Hypoxic Hypoxia and Brain Function in Military Aviation, Tab. 2", "pmc.ncbi.nlm.nih.gov/articles/PMC8171399", "A"],
        ["P2", "Intensita' allenamento ISS (66-75 % del picco di FC)", "NASA OCHMO-TB-031 Exercise overview; studio ISS sull'esercizio", "nasa.gov/ochmo-tb-031-exercise-overview-2 ; pmc.ncbi.nlm.nih.gov/articles/PMC7434884", "B"],
        ["P3", "FC e VO2 proporzionali (effetto sforzo)", "Relationship between %HRR and %VO2R in treadmill exercise", "pubmed.ncbi.nlm.nih.gov/9502363", "B"],
        ["P4", "FC nel sonno 20-30 % sotto il riposo", "Cleveland Clinic, sleeping heart rate", "health.clevelandclinic.org/sleeping-heart-rate", "B"],
        ["P5", "Normali: respirazione 12-20/min, SpO2 96-100 %", "OpenStax Clinical Nursing Skills, 15.6", "openstax.org/books/clinical-nursing-skills/pages/15-6-respiration", "A"],
        ["P7", "Recupero FC dopo sforzo (tau 65 s)", "Exponential modelling of heart rate recovery after maximal exercise", "ijpp.com/exponential-modelling-of-heart-rate-recovery-after-a-maximal-exercise", "B"],
        ["P8", "Febbre: +8.5 bpm per grado C", "Fever and cardiac rhythm; Body temperature and heart rate", "pubmed.ncbi.nlm.nih.gov/2424378 ; journalfeed.org/?p=2902", "B"],
        ["P9", "Fibrillazione: RR irregolari, RMSSD piu' alto", "HRV in AF and hypertension (Eur J Clin Invest 2021); AMBOSS AF con risposta ventricolare rapida", "onlinelibrary.wiley.com/doi/full/10.1111/eci.13361", "B"],
        ["P10", "FC durante EVA (media 131-135 bpm, picchi ~162)", "NASA: Physical exertion and metabolic demand of EVA (NTRS 19910001262)", "ntrs.nasa.gov/citations/19910001262", "B"],
        ["P11", "Pressione e O2 delle tute (EMU 222 mmHg 100 % O2; Marte 8.2 psia 34 %)", "NASA EVA Operations, cap. 5.4; OCHMO-TB-037", "nasa.gov/wp-content/uploads/2023/03/gernhardt-eva-ops-chp-5.4-2013.pdf", "A/B"],
        ["P12", "Limiti e sintomi della CO2", "NASA OCHMO-TB-004 Carbon dioxide", "nasa.gov/wp-content/uploads/2023/12/ochmo-tb-004-carbon-dioxide.pdf", "A"],
        ["-", "Limiti di pressione, PIO2, T, UR usati come allarmi", "NASA-STD-3001 (via docs/reference/ambientmonitor)", "-", "A"],
        ["E", "Disidratazione, stress, nausea, HRV, risposta alla CO2, SpO2 in AF, effetto decompressione", "Nessuna fonte quantitativa trovata: stima nostra (ESTIMATE)", "-", "E"],
    ], columns=["Tag", "Cosa supporta", "Fonte", "Dove (URL abbreviato)", "Aff."])

    with PdfPages(OUT / "report.pdf") as pdf:
        text_page(pdf, "ARES 3 - Dati prodotti dagli astronauti simulati: verifica", scope, size=9.0, wrap=120)
        text_page(pdf, "Ambiente e assunzioni della simulazione", env_text, size=8.6, wrap=130)
        table_page(pdf, "Glossario e limiti di sicurezza NASA usati come allarmi", limits,
                   "Un 'allarme' nella simulazione significa che il valore VERO di un modulo ha superato uno di questi limiti (NASA-STD-3001, standard di salute e prestazioni degli equipaggi). "
                   "Non e' una diagnosi sull'astronauta.", col_w=[0.15, 0.22, 0.45, 0.18], font=8, scale=2.4)
        table_page(pdf, "Variabili prodotte dalla simulazione", variables,
                   "Gli intervalli sono quelli osservati in un giorno normale (4 astronauti). Gli scenari possono uscire da questi intervalli.",
                   col_w=[0.17, 0.08, 0.2, 0.37, 0.18], font=7.5, scale=2.2)
        text_page(pdf, "Come funziona il modello dei vitali", model_text, size=9.0, wrap=120)
        text_page(pdf, "Come leggere i grafici", guide, size=9.0, wrap=120)
        table_page(pdf, "Dati che i moduli di Luca si aspettano e dove li prendiamo", luca_inputs,
                   "Elenco ricavato dai notebook di Luca (ECG IMPROVEMENTFINAL, Critical_condition_monitor, ENERGY_INTAKE_HYDRATION, stress-level-detection). "
                   "Nota sui nomi: 'oxygen_perc' e' la SpO2 (sangue), 'oxygenperc' e' la percentuale di ossigeno della miscela respirata.",
                   col_w=[0.21, 0.19, 0.25, 0.17, 0.18], font=6.6, scale=2.15)
        params = pd.DataFrame([
            ["FC a riposo", "65 bpm (comandante 64)", "ESTIMATE; intervallo clinico 60-100", "E"],
            ["FC nel sonno", "80 % del riposo (~52 bpm)", "20-30 % piu' bassa [P4]", "B"],
            ["FC sotto sforzo", "riposo + (185 - riposo) x (MET-1)/9", "FC e VO2 lineari [P3]", "B"],
            ["FC recupero / salita", "tau 65 s / 40 s", "[P7] / ESTIMATE", "B/E"],
            ["FC con poco ossigeno", "+0.5 bpm per mmHg sotto PIO2 127, massimo +40", "ESTIMATE", "E"],
            ["SpO2", "98 % a riposo; scende secondo la curva PIO2->SpO2", "[P1] tra 70 e 99 mmHg, sotto ESTIMATE; 96-100 % [P5]", "A/E"],
            ["Freq. respiratoria", "14/min (sonno 12) + 1.5 per MET", "12-20/min [P5]; incremento ESTIMATE", "A/E"],
            ["HRV (RMSSD)", "45 ms a riposo, scende con la FC, +-10 % nel giorno", "ESTIMATE", "E"],
            ["Temperatura cutanea", "33.5 C + 0.05 per MET, +0.6 nel sonno", "ESTIMATE", "E"],
            ["CO2 -> FC / respirazione", "+1 bpm e +1.5/min per mmHg sopra 2", "ESTIMATE (sintomi a 3.5 mmHg [P12])", "E"],
            ["Febbre", "+13 bpm per +1.5 C", "8.5 bpm per grado C [P8]", "B"],
            ["Fibrillazione", "FC 150, SpO2 93 (brief), HRV x2", "FC>100-110 [P9]; SpO2 e HRV ESTIMATE", "B/E"],
            ["Disidratazione, stress, nausea", "FC +10-12, HRV x0.6-0.85, respirazione +1-2", "nessuna fonte quantitativa", "E"],
        ], columns=["Grandezza", "Valore nel modello", "Fonte / nota", "Aff."])
        table_page(pdf, "Parametri del modello e loro fonti", params,
                   "I tag [P1]-[P12] sono spiegati con il titolo della fonte nell'ultima pagina. Aff.: A letta direttamente, B letta tramite riassunto da riverificare, E = ESTIMATE, nessuna fonte.",
                   col_w=[0.18, 0.34, 0.38, 0.06], font=8)

        # ---- one page per NPC: normal day
        for n in NPCS:
            fig, axes = plt.subplots(7, 1, figsize=(11.69, 8.27), sharex=True,
                                     gridspec_kw={"height_ratios": [0.4, 2, 1.3, 1.3, 1.3, 1.3, 1.3]})
            h = hours(day)
            activity_strip(axes[0], day, n)
            axes[0].set_ylabel("attivita'", fontsize=6, rotation=0, labelpad=26)
            keys = ["hr", "spo2", "rr", "hrv", "skin"]
            for ax, k in zip(axes[1:6], keys):
                ax.plot(h, day["df"][f"{n}_{k}"], color=COL[n], lw=0.9)
                ax.set_ylabel(METRICS[k][0], fontsize=7)
                ax.tick_params(labelsize=7)
                if k in ("hr", "spo2") and n in LUCA:
                    pass
            axes[1].axhline(LUCA[n]["hr"], color="k", ls=":", lw=0.8)
            axes[1].text(h[0] + 0.1, LUCA[n]["hr"], f" Luca {LUCA[n]['hr']}", fontsize=6, va="bottom")
            axes[2].axhline(LUCA[n]["spo2"], color="k", ls=":", lw=0.8)
            axes[2].text(h[0] + 0.1, LUCA[n]["spo2"], f" Luca {LUCA[n]['spo2']}", fontsize=6, va="bottom")
            ax = axes[6]
            ax.plot(h, day["df"][f"{n}_mod"].astype("category").cat.codes, color="#555", lw=0.8, drawstyle="steps-post")
            cats = list(day["df"][f"{n}_mod"].astype("category").cat.categories)
            ax.set_yticks(range(len(cats)))
            ax.set_yticklabels(cats, fontsize=6)
            ax.set_ylabel("modulo", fontsize=7)
            ax.set_xlabel("ora locale (h, oltre 24 = giorno dopo)", fontsize=8)
            ax.set_xlim(h[0], h[-1])
            handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in ACT_COL.values()]
            fig.legend(handles, list(ACT_COL), ncol=8, fontsize=6, loc="upper right", frameon=False)
            fig.suptitle(f"{NAME[n]} - giornata nominale (stazione 758 mmHg, 21 % O2). Linea punteggiata = valore di Luca",
                         fontsize=10, x=0.02, ha="left")
            fig.tight_layout(rect=(0, 0.03, 1, 0.96))
            caption(fig, "Asse orizzontale: ora locale. Asse verticale di ogni pannello: la grandezza nel titolo con unita' (FC bpm, SpO2 %, respirazione atti/min, HRV ms, temperatura cutanea C). "
                         "Striscia in alto = attivita'; striscia in basso = modulo; linea punteggiata = valore indicato da Luca.")
            pdf.savefig(fig)
            plt.close(fig)

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
                         f"{r.skin:.1f}", "OK" if ref and not flags else ("; ".join(flags) if flags else "-")])
        table_page(pdf, "Media per attivita' nel giorno nominale e verifica sui riferimenti", pd.DataFrame(
            rows, columns=["Luca", "NPC", "Attivita'", "min", "FC", "SpO2", "FR", "HRV", "T cut.", "Verifica"]),
            "Riferimenti (ESTIMATE di lavoro): sonno FC 40-60 [P4]; veglia a riposo FC 60-100, SpO2 95-100, FR 12-20 [P5]; esercizio ISS 66-75 % del picco "
            "(122-139 bpm su 185) [P2]. Le attivita' con 'fuori' non sono errori: sono i punti da guardare insieme a Luca.",
            col_w=[0.07, 0.05, 0.14, 0.05, 0.05, 0.06, 0.05, 0.05, 0.06, 0.30], font=6.8, scale=1.25)

        # ---- environment of the day
        fig, axes = plt.subplots(2, 3, figsize=(11.69, 8.27), sharex=True)
        h = hours(day)
        for ax, (c, t, lim) in zip(axes.flat, [("hab_ppCO2", "ppCO2 habitat (mmHg)", 3.0), ("hab_PIO2", "PIO2 habitat (mmHg)", 122),
                                               ("hab_T", "T habitat (C)", 27), ("hab_RH", "Umidita' habitat (%)", 75),
                                               ("hab_P", "Pressione habitat (mmHg)", None), ("eva_PIO2", "PIO2 modulo EVA (mmHg)", 122)]):
            ax.plot(h, day["df"][c], lw=0.8)
            if lim is not None:
                ax.axhline(lim, color="k", ls="--", lw=0.8)
            ax.set_title(t, fontsize=9)
            ax.tick_params(labelsize=7)
        fig.suptitle("Ambiente nella giornata nominale (tratteggio = limite NASA-STD-3001)", fontsize=11)
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        caption(fig, "Asse orizzontale: ora locale. Asse verticale: grandezza nel titolo (ppCO2 e PIO2 in mmHg, temperatura in C, umidita' in %, pressione in mmHg). Tratteggio = limite NASA. "
                     "Nelle ultime due colonne a destra, il modulo EVA e' vuoto per quasi tutto il giorno.")
        pdf.savefig(fig)
        plt.close(fig)

        scen_rows = [[ev, EV_IT[ev][0], EV_IT[ev][1], EV_IT[ev][2], EV_IT[ev][3]] for ev in EVENTS]
        table_page(pdf, "Scenari simulati", pd.DataFrame(scen_rows, columns=["Codice", "Situazione", "Quando", "Cosa succede", "Origine dei valori"]),
                   "Ogni scenario simula la stessa giornata di routine; cambia solo l'evento. Lo stato 'nominal' / il nome dell'evento sono le etichette scritte nei dati per il modello di allerta.",
                   col_w=[0.10, 0.15, 0.11, 0.32, 0.32], font=6.8, scale=2.6)

        # ---- events
        EVDEF = {
            "eva_nominal": ("med", ["hr", "spo2", "rr", "hrv"], [("eva", "P", None), ("eva", "PIO2", 122), ("eva", "ppCO2", 3.0)], (9.0, 11.5)),
            "eva_decompression": ("med", ["hr", "spo2", "rr", "hrv"], [("eva", "P", None), ("eva", "PIO2", 122), ("eva", "ppCO2", 3.0)], (9.5, 11.5)),
            "fibrillation": ("eng", ["hr", "spo2", "rr", "hrv"], [], (10.0, 13.0)),
            "scrubber_failure": ("cmd", ["hr", "rr", "spo2", "hrv"], [("hab", "ppCO2", 3.0), ("hab", "T", 27)], (12.0, 26.0)),
            "co2_release": ("cmd", ["hr", "rr", "spo2", "hrv"], [("hab", "ppCO2", 3.0), ("hab", "PIO2", 122)], (12.0, 20.0)),
            "slow_leak": ("cmd", ["hr", "spo2", "rr", "hrv"], [("hab", "P", None), ("hab", "PIO2", 122), ("hab", "ppCO2", 3.0)], (12.0, 22.0)),
            "dehydration": ("bot", ["hr", "hrv", "rr", "skin"], [], (6.0, 20.0)),
            "stress": ("cmd", ["hr", "hrv", "rr", "skin"], [], (8.0, 14.0)),
            "fever": ("med", ["hr", "skin", "rr", "hrv"], [], (10.0, 20.0)),
            "motion_sickness": ("bot", ["hr", "rr", "hrv", "skin"], [], (7.0, 13.0)),
        }
        for ev in EVENTS:
            r = R[ev]
            npc, mets, envs, (x0, x1) = EVDEF[ev]
            h = hours(r)
            title_it, when, what, origin, check = EV_IT[ev]
            desc = f"{what} Quando: {when}. Origine dei valori: {origin}"
            n_pan = len(mets) + len(envs)
            cols = 3 if n_pan > 4 else 2
            fig = plt.figure(figsize=(11.69, 8.27))
            fig.text(0.03, 0.97, f"{title_it}  -  {NAME[npc]}", fontsize=13, weight="bold", va="top")
            fig.text(0.03, 0.94, "\n".join(textwrap.wrap(desc, 175)), fontsize=8, va="top")
            fig.text(0.03, 0.072, "Da verificare: " + check, fontsize=8, weight="bold", va="top", wrap=True)
            caption(fig, "Asse orizzontale: ora locale. Asse verticale: grandezza nel titolo di ogni pannello (unita' tra parentesi o nel nome). Area rosa = evento attivo; tratteggio = limite NASA. "
                         "Tabella: media 30 min prima, minimo e massimo durante l'evento, media 30 min dopo.", y=0.004)
            rows_n = math.ceil(n_pan / cols)
            gs = fig.add_gridspec(rows_n + 1, cols, top=0.88, bottom=0.10, hspace=0.55, wspace=0.25,
                                  height_ratios=[1] * rows_n + [0.9])
            panels = [(f"{npc}_{k}", METRICS[k][0], None) for k in mets] + [(f"{m}_{k}", f"{m}: {k}", lim) for m, k, lim in envs]
            for i, (c, t, lim) in enumerate(panels):
                ax = fig.add_subplot(gs[i // cols, i % cols])
                ax.plot(h, r["df"][c], color=COL[npc] if c.startswith(npc) else "#1f77b4", lw=0.9)
                if c == f"{npc}_hr_s":
                    pass
                if lim is not None:
                    ax.axhline(lim, color="k", ls="--", lw=0.7)
                shade_faults(ax, r)
                ax.set_xlim(x0, min(x1, h[-1]))
                ax.set_title(t, fontsize=8)
                ax.tick_params(labelsize=6)
            # stats table: pre / extreme in fault window / post
            axt = fig.add_subplot(gs[rows_n, :])
            axt.axis("off")
            f0 = min(f["start"] for f in r["faults"]) if r["faults"] else None
            f1 = max(min(f["end"], r["df"]["t"].iloc[-1]) for f in r["faults"]) if r["faults"] else None
            d = r["df"]
            trows = []
            for k in mets:
                s = d[f"{npc}_{k}"]
                if f0 is None:
                    sel = d[d[f"{npc}_mod"] == "eva"] if ev == "eva_nominal" else d
                    trows.append([METRICS[k][0], f"{sel[f'{npc}_{k}'].mean():.1f}", f"{sel[f'{npc}_{k}'].min():.1f}", f"{sel[f'{npc}_{k}'].max():.1f}", "-"])
                    continue
                pre = s[(d.t >= f0 - 1800) & (d.t < f0)].mean()
                win = s[(d.t >= f0) & (d.t <= f1)]
                post = s[(d.t > f1) & (d.t <= f1 + 1800)].mean()
                trows.append([METRICS[k][0], f"{pre:.1f}", f"{win.min():.1f}", f"{win.max():.1f}", f"{post:.1f}" if not np.isnan(post) else "-"])
            head = ["Grandezza", "prima (30 min)" if f0 is not None else "media (EVA)", "min nell'evento" if f0 is not None else "min",
                    "max nell'evento" if f0 is not None else "max", "dopo (30 min)"]
            tb = axt.table(cellText=trows, colLabels=head, loc="upper left", cellLoc="left", colWidths=[0.15, 0.10, 0.10, 0.10, 0.10])
            tb.auto_set_font_size(False)
            tb.set_fontsize(7)
            tb.scale(1, 1.2)
            al = r["alarms"]
            if len(al):
                g = al.groupby(["code", "module"]).agg(first=("t", "min"), last=("t", "max"), n=("t", "count")).reset_index()
                txt = "Allarmi NASA: " + "; ".join(f"{x.code}/{x.module} {(r['start_tod'] + x['first'] / 3600) % 24:.2f}h-{(r['start_tod'] + x['last'] / 3600) % 24:.2f}h ({x.n}s)"
                                                   for _, x in g.iterrows())
            else:
                txt = "Allarmi NASA: nessuno."
            labs = d[f"{npc}_anom"].value_counts()
            txt += "\nEtichette dataset per " + npc + ": " + ", ".join(f"{k} {v}s" for k, v in labs.items())
            fig.text(0.62, 0.20, "\n".join(textwrap.wrap(txt, 70)), fontsize=7, va="top")
            pdf.savefig(fig)
            plt.close(fig)

        # ---- Luca declared vs model
        rows = []

        def win(r, n, c, lo, hi):
            d = r["df"]
            sel = d[(d["tod"] >= lo) & (d["tod"] < hi)] if "tod" in d else d
            return sel[f"{n}_{c}"].mean()

        rows.append(["ASTRO_01 lavoro 7-12 h", "69.5 / 98.5", f"{win(day, 'cmd', 'hr', 7, 12):.0f} / {win(day, 'cmd', 'spo2', 7, 12):.1f}",
                     f"{win(daym, 'cmd', 'hr', 7, 12):.0f} / {win(daym, 'cmd', 'spo2', 7, 12):.1f}", "stazione: PIO2 149"])
        rows.append(["ASTRO_02 T2 17:00-17:45", "142.5 / 96.2", f"{win(day, 'bot', 'hr', 17.1, 17.75):.0f} / {win(day, 'bot', 'spo2', 17.1, 17.75):.1f}",
                     f"{win(daym, 'bot', 'hr', 17.1, 17.75):.0f} / {win(daym, 'bot', 'spo2', 17.1, 17.75):.1f}", "MET 7.0 scelto per HR ~ 142"])
        rows.append(["ASTRO_03 fibrillazione", "150 / 93", f"{fib_w['eng_hr'].mean():.0f} / {fib_w['eng_spo2'].mean():.1f}", "-", "imposto da Luca (hr_to, spo2_to)"])
        rows.append(["ASTRO_04 EVA nominale", "132.5 / 94", f"{eva_hr:.0f} / {eva_sp:.1f}", "-", f"PIO2 EVA {eva_pio2:.0f} mmHg"])
        rows.append(["ASTRO_04 EVA emergenza", "172 / 88", f"{dec_hr_max:.0f} / {dec_sp_min:.0f}", "-", f"PIO2 {dec_pio2:.1f}: coscienza persa, non modellata"])
        table_page(pdf, "Valori di Luca (FC / SpO2) contro il modello",
                   pd.DataFrame(rows, columns=["Situazione", "Luca FC / SpO2", "Modello: stazione 758 mmHg (adottata)", "Modello: habitat Marte (confronto)", "Nota"]),
                   "Dove la differenza e' grande il modello segue le fonti [P1][P2]; non significa che il modello abbia ragione: serve la decisione di Luca "
                   "(vedi incongruenze 2, 3 e domanda 1). SpO2 in decompressione: valore minimo; FC: massimo.", col_w=[0.20, 0.14, 0.18, 0.18, 0.30], font=8)

        text_page(pdf, "Incongruenze nel brief ricevuto", incong, size=8.4, wrap=135)
        table_page(pdf, "Monitor atmosfera di Luca applicato alla simulazione (1 campione al minuto)",
                   pd.DataFrame(atm_rows, columns=["Atmosfera simulata", "Luogo", "Minuti occupati", "ppO2 = P x %O2 (mmHg)", "Esito della funzione"]),
                   "La funzione di Luca segnala 'CRITICAL ipossia' quando ppO2 (pressione totale x frazione di O2) e' sotto 148 mmHg o l'O2 e' sotto 19.5 %: soglie da livello del mare (758 mmHg x 19.5 % = 148). "
                   "Con l'atmosfera della stazione (758 x 21 % = 159) non scatta; con la tuta (350 mmHg x 42 % = 147) e con l'habitat marziano (527 x 26.5 % = 140) scatta anche in condizioni nominali. NASA usa invece la PIO2 (che sottrae 47 mmHg di vapore acqueo) con limite 122-127 mmHg. "
                   "Inoltre il limite di O2 alto (23.5 %, rischio incendio) e' pensato per una cabina: in una tuta, per sua natura, l'O2 e' piu' alto (28 % nel brief, 42 % nella nostra assunzione) e la funzione segnala sempre allarme. Serve decidere quali criteri valgono per la tuta (domande 2 e 6).",
                   col_w=[0.26, 0.10, 0.10, 0.16, 0.38], font=7.5, scale=2.2)

        # ---- Luca's rules on simulated EVA values
        sub = []
        for lbl, r in (("EVA nominale", ev_nom), ("EVA decompressione", ev_dec)):
            d = r["df"][r["df"]["med_mod"] == "eva"]
            alt_i = d["eva_P"].map(isa_altitude_m)
            alt_e = d["eva_PIO2"].map(pio2_equiv_altitude_m)
            st = alt_e.map(monitor_analysis).value_counts()
            o2m = alt_e.map(lambda a: o2_minimum(a * 3.28084 if np.isfinite(a) else 1e9)).max()
            sub.append([lbl, f"{alt_i.median():,.0f}", f"{alt_e.replace(np.inf, np.nan).median():,.0f}",
                        ", ".join(f"{k}: {v}s" for k, v in st.items()), f"{o2m} % / {d['eva_o2pct'].median():.0f} %"])
        table_page(pdf, "Regole di Luca applicate ai valori simulati dell'EVA",
                   pd.DataFrame(sub, columns=["Scenario", "Alt. da pressione (m)", "Alt. equiv. PIO2 (m)", "Stato ipossia (secondi)", "O2 min richiesto / attuale"]),
                   "Alt. da pressione = atmosfera standard ISA invertita; alt. equiv. PIO2 = quota in aria con la stessa PIO2 (piu' fisiologica). 'inf' = nessun O2 inspirato.",
                   col_w=[0.15, 0.15, 0.15, 0.35, 0.15], font=8)
        csv_tab = {1000: ("NOMINALE", 21), 3000: ("PRE-ALLERTA", 27), 5500: ("PERICOLO AVANZATO", 44), 7000: ("CRITICO ELEVATO", 78),
                   12000: ("EMERGENZA SPAZIALE", 100)}
        cmp_rows = [[h, monitor_analysis(h), o2_minimum(h * 3.28084), st, o2, f"{isa_mmhg(h):.0f}"] for h, (st, o2) in csv_tab.items()]
        table_page(pdf, "Due tabelle di soglie in conflitto: notebook vs monitor_parametri_spaziali.csv",
                   pd.DataFrame(cmp_rows, columns=["Quota (m)", "Stato (notebook)", "O2 min % (notebook)", "Stato (CSV)", "O2 min % (CSV)", "Pressione ISA (mmHg)"]),
                   "Stato ipossia e O2 minimo differiscono tra le due fonti di Luca. Va deciso quale vale.", font=8)

        # ---- ECG
        fig, axes = plt.subplots(3, 2, figsize=(11.69, 8.27))
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
        fig.suptitle("ECG assegnati agli NPC", fontsize=12)
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        caption(fig, "Asse orizzontale: campione del battito (140 per riga). Asse verticale: ampiezza normalizzata del segnale. Blu = battito normale (label 1.0), rosso = anomalo (label 0.0).")
        pdf.savefig(fig)
        plt.close(fig)

        # ---- SpO2 curve + open questions + sources
        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        xs, ys = zip(*SPO2_VS_PIO2)
        ax.plot(xs, ys, "o-", color="#1f77b4")
        for label, x in (("habitat Marte 127", 127), ("sup. nominale 85 (EVA Luca)", 85), ("limite NASA 122", 122), ("ISS 149", 149)):
            ax.axvline(x, color="#999", ls=":", lw=0.8)
            ax.text(x, 12, label, rotation=90, fontsize=7, va="bottom")
        ax.set_xlabel("PIO2 (mmHg)")
        ax.set_ylabel("SpO2 stazionaria (%)")
        ax.set_title("Curva SpO2 contro PIO2 usata dal modello [P1] (sotto 70 mmHg: ESTIMATE)")
        caption(fig, "Asse orizzontale: PIO2 = pressione parziale dell'ossigeno inspirato (mmHg) = (pressione totale - 47) x frazione di O2. Asse verticale: SpO2 stazionaria (%). "
                     "Le linee verticali sono i valori incontrati nelle simulazioni: 85 = EVA con 28 % O2 (brief), 122 = limite NASA, 127 = EVA assunta e habitat Marte, 149 = aria della stazione (adottata).")
        pdf.savefig(fig)
        plt.close(fig)

        text_page(pdf, "Domande per Luca", questions, size=8.6, wrap=135)
        src_rows = sources.copy()
        for c, w in (("Cosa supporta", 38), ("Fonte", 48), ("Dove (URL abbreviato)", 52)):
            src_rows[c] = src_rows[c].map(lambda x, w=w: "\n".join(textwrap.wrap(str(x), w)))
        table_page(pdf, "Fonti", src_rows, "Ricerca online del 2026-11-14. Elenco con URL completi: docs/reference/physiology-sources.md.",
                   col_w=[0.04, 0.27, 0.32, 0.33, 0.04], font=7, scale=3.0)

    print(f"report: {OUT / 'report.pdf'}")


if __name__ == "__main__":
    main()
