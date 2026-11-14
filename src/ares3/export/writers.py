"""Chunked dataset writer: bounded memory for unbounded runs.

Output layout::

    <out>/manifest.json            scenario, seed, dt, schema, columns
    <out>/scenario.json            the fully resolved scenario (reproducibility)
    <out>/long/part-000000.parquet one row per (timestamp, sensor): the ground-truth dataset
    <out>/wide/part-000000.parquet one row per timestamp, one column per sensor

A part file is written every ``chunk_hours`` of SIMULATED time, so days of simulation never pile up in
memory and a crashed run keeps everything flushed so far.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ares3 import __version__
from ares3.core.engine import StepResult
from ares3.schemas.scenario import ExportConfig, Scenario

SCHEMA = "ares3.dataset/1"
LONG_COLUMNS = ["tick", "timestamp", "sensor_id", "entity_id", "metric", "value", "value_true",
                "is_anomaly", "anomaly_type", "anomaly_ids"]


class DatasetWriter:
    def __init__(self, out_dir: str | Path, scenario: Scenario) -> None:
        cfg: ExportConfig = scenario.file.export
        self.cfg = cfg
        self.out = Path(out_dir)
        self.chunk_ticks = max(1, round(cfg.chunk_hours * 3600.0 / scenario.file.dt_s))
        self.sensor_ids = [s.id for s in scenario.layout.sensors]
        self._long: list[dict] = []
        self._wide: dict[int, dict] = {}
        self._part = 0
        self._ticks_in_chunk = 0
        self._rows_written = 0
        for sub in (["long"] if cfg.long else []) + (["wide"] if cfg.wide else []):
            (self.out / sub).mkdir(parents=True, exist_ok=True)
        (self.out / "scenario.json").write_text(scenario.model_dump_json(indent=2), encoding="utf-8")
        self._manifest = {
            "schema": SCHEMA, "ares3_version": __version__, "scenario": scenario.file.name, "seed": scenario.file.seed,
            "dt_s": scenario.file.dt_s, "environment": scenario.environment.name, "format": cfg.format,
            "long_columns": LONG_COLUMNS, "wide_sensor_columns": self.sensor_ids,
        }

    def add(self, result: StepResult) -> None:
        for row in result.rows:
            self._long.append(row)
            if self.cfg.wide:
                w = self._wide.setdefault(row["tick"], {"tick": row["tick"], "timestamp": row["timestamp"],
                                                        "anomaly_any": False, "anomaly_types": ""})
                w[row["sensor_id"]] = row["value"]
                if row["is_anomaly"]:
                    w["anomaly_any"] = True
                    types = set(filter(None, w["anomaly_types"].split("|"))) | {row["anomaly_type"]}
                    w["anomaly_types"] = "|".join(sorted(types))
        self._ticks_in_chunk += 1
        if self._ticks_in_chunk >= self.chunk_ticks:
            self.flush()

    def _write(self, df: pd.DataFrame, sub: str) -> None:
        path = self.out / sub / f"part-{self._part:06d}.{self.cfg.format}"
        if self.cfg.format == "parquet":
            df.to_parquet(path, index=False)
        else:
            df.to_csv(path, index=False)

    def flush(self) -> None:
        if self._long and self.cfg.long:
            self._write(pd.DataFrame.from_records(self._long, columns=LONG_COLUMNS), "long")
        if self._wide and self.cfg.wide:
            cols = ["tick", "timestamp", *self.sensor_ids, "anomaly_any", "anomaly_types"]
            self._write(pd.DataFrame.from_records(list(self._wide.values())).reindex(columns=cols), "wide")
        self._rows_written += len(self._long)
        if self._long or self._wide:
            self._part += 1
        self._long, self._wide, self._ticks_in_chunk = [], {}, 0

    def close(self) -> None:
        self.flush()
        self._manifest.update({"parts": self._part, "long_rows": self._rows_written})
        (self.out / "manifest.json").write_text(json.dumps(self._manifest, indent=2), encoding="utf-8")
