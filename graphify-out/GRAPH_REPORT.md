# Graph Report - .  (2026-11-14)

## Corpus Check
- Corpus is ~31,259 words - fits in a single context window. You may not need a graph.

## Summary
- 541 nodes · 1237 edges · 28 communities (24 shown, 4 thin omitted)
- Extraction: 67% EXTRACTED · 33% INFERRED · 0% AMBIGUOUS · INFERRED: 412 edges (avg confidence: 0.53)
- Token cost: 74,307 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Clock & Alarm Monitor|Clock & Alarm Monitor]]
- [[_COMMUNITY_Dataset Export Writers|Dataset Export Writers]]
- [[_COMMUNITY_BodyHologram Component|BodyHologram Component]]
- [[_COMMUNITY_Engine Tick Loop & Constants|Engine Tick Loop & Constants]]
- [[_COMMUNITY_World Physics & Atmosphere|World Physics & Atmosphere]]
- [[_COMMUNITY_Scenario Config & NASA Limits|Scenario Config & NASA Limits]]
- [[_COMMUNITY_CLI & Engine Runner|CLI & Engine Runner]]
- [[_COMMUNITY_Dashboard Dependencies|Dashboard Dependencies]]
- [[_COMMUNITY_Life-Support Actuators|Life-Support Actuators]]
- [[_COMMUNITY_Sensors & Metrics|Sensors & Metrics]]
- [[_COMMUNITY_TS App Config|TS App Config]]
- [[_COMMUNITY_TS Node Config|TS Node Config]]
- [[_COMMUNITY_Alarm Rules|Alarm Rules]]
- [[_COMMUNITY_Typedoc Config|Typedoc Config]]
- [[_COMMUNITY_Baseline Physiology|Baseline Physiology]]
- [[_COMMUNITY_Telemetry Contracts|Telemetry Contracts]]
- [[_COMMUNITY_Dashboard Docs & Licensing|Dashboard Docs & Licensing]]
- [[_COMMUNITY_Lint Config|Lint Config]]
- [[_COMMUNITY_Layering Test|Layering Test]]
- [[_COMMUNITY_Labelling & Export Format|Labelling & Export Format]]
- [[_COMMUNITY_TS Project Refs|TS Project Refs]]
- [[_COMMUNITY_Package Root|Package Root]]
- [[_COMMUNITY_Core Package|Core Package]]
- [[_COMMUNITY_Plugins Package|Plugins Package]]

## God Nodes (most connected - your core abstractions)
1. `ModuleState` - 36 edges
2. `Engine` - 34 edges
3. `StepContext` - 32 edges
4. `Observation` - 31 edges
5. `World` - 30 edges
6. `NPCState` - 30 edges
7. `Command` - 28 edges
8. `Scenario` - 25 edges
9. `BaseActuator` - 25 edges
10. `StepResult` - 23 edges

## Surprising Connections (you probably didn't know these)
- `test_metabolism_reproduces_bvad_at_reference_mass()` --calls--> `rates_for()`  [INFERRED]
  tests/test_engine.py → src/ares3/core/metabolism.py
- `Output Format (long/wide parquet, manifest)` --semantically_similar_to--> `Chunked Parquet/CSV Export`  [INFERRED] [semantically similar]
  README.md → CLAUDE.md
- `test_closed_system_conserves_every_species()` --calls--> `Engine`  [INFERRED]
  tests/test_engine.py → src/ares3/core/engine.py
- `test_emergency_labels_follow_the_fault_window()` --calls--> `Engine`  [INFERRED]
  tests/test_engine.py → src/ares3/core/engine.py
- `test_nominal_hour_has_no_alarm_or_label()` --calls--> `Engine`  [INFERRED]
  tests/test_engine.py → src/ares3/core/engine.py

## Import Cycles
- 1-file cycle: `dashboard/src/data/anatomy.ts -> dashboard/src/data/anatomy.ts`

## Hyperedges (group relationships)
- **Scenario composition from layout, crew, faults, environment** — scenarios_emergency, scenarios_mars_surface, scenarios_base_layout, scenarios_sensors_placeholder, scenarios_actuators_placeholder, scenarios_crew, scenarios_faults [EXTRACTED 0.95]

## Communities (28 total, 4 thin omitted)

### Community 0 - "Clock & Alarm Monitor"
Cohesion: 0.12
Nodes (51): ABC, AlarmMonitor, Hours of the local day in [0, 24); a day is always 24 'local hours' long., SimClock, StepResult, NPC, BaseActuator, BaseAgent (+43 more)

### Community 1 - "Dataset Export Writers"
Cohesion: 0.07
Nodes (44): BaseModel, DataFrame, DatasetWriter, Chunked dataset writer: bounded memory for unbounded runs.  Output layout::, CrewConfig, CrewMember, PhysiologySpec, Crew configuration: astronaut profiles, daily schedules and the metabolic activi (+36 more)

### Community 2 - "BodyHologram Component"
Cohesion: 0.08
Nodes (43): BodyHologram(), BaseGlowGeometry, BodyHologramProps, BodyHologramViewModel, OrganPartRenderData, OrganRenderData, clampSeverity(), COLOR_CRITICAL (+35 more)

### Community 3 - "Engine Tick Loop & Constants"
Cohesion: 0.07
Nodes (34): Discrete simulation clock. Time of day follows the environment profile's day len, inspired_po2_mmhg(), Physical constants and moist-air thermodynamics (SI unless noted). Ported from a, PIO2 = (PB - 47 mmHg) * FO2 [S20], FO2 the dry O2 fraction ``pO2 / (P - pv)``., The tick loop. One ``Engine.step()`` runs these phases in a fixed, documented or, FaultInjector, label_row(), Fault injection: which faults are active, their effect on sensor readings, and g (+26 more)

### Community 4 - "World Physics & Atmosphere"
Cohesion: 0.11
Nodes (18): Atmosphere, psat_kpa(), Saturation vapour pressure of water in kPa (Magnus formula, over ice below 0 deg, HatchRT, initial_inventory(), ModuleRT, Mutable physical state: a topological graph of modules with gas inventories (mol, Vapour above saturation condenses and leaves the air (booked in the ledger). (+10 more)

### Community 5 - "Scenario Config & NASA Limits"
Cohesion: 0.09
Nodes (33): BVAD metabolism data, Mars exterior temperature profiles, Habitat atmosphere 70.3 kPa / 26.5% O2, Mars sol 88775.244 s, NASA-STD-3001, O2 emergency mode, PIO2 oxygen alarms, Life-support power bus priority (+25 more)

### Community 6 - "CLI & Engine Runner"
Cohesion: 0.11
Nodes (20): Command line: ``ares3 run scenarios/nominal.yaml -o output/run1 --days 2``., _run(), _validate(), Engine, Yield ``ticks`` results, or forever when ``ticks`` is None (stop by breaking out, Namespace, Plugin resolution. ``kind`` in YAML is either ``"package.module:ClassName"`` (an, register() (+12 more)

### Community 7 - "Dashboard Dependencies"
Cohesion: 0.07
Nodes (28): dependencies, react, react-dom, devDependencies, oxlint, react-doctor, typedoc, @types/node (+20 more)

### Community 8 - "Life-Support Actuators"
Cohesion: 0.13
Nodes (18): CO2Scrubber, Dehumidifier, _DehumParams, _Hysteresis, O2Generator, _O2GenParams, _PressureParams, PressureRegulator (+10 more)

### Community 9 - "Sensors & Metrics"
Cohesion: 0.12
Nodes (15): BaseSensor, module_metric(), npc_metric(), T [degC], RH [%], ppCO2 [mmHg], pO2 [kPa], PIO2 [mmHg], P [kPa]., A vital sign (``hr``, ``spo2``, ...) or one of ``met``, ``vo2_l_min``, ``vco2_l_, ModuleSensor, PLACEHOLDER - awaiting review by Mario (sensor physics) and Luca (wearable metri, Ambient probe in a module: ``target: module:<id>``, metric one of T, RH, ppCO2, (+7 more)

### Community 10 - "TS App Config"
Cohesion: 0.10
Nodes (19): compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection (+11 more)

### Community 11 - "TS Node Config"
Cohesion: 0.12
Nodes (16): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+8 more)

### Community 12 - "Alarm Rules"
Cohesion: 0.23
Nodes (8): AlarmEvent, AlarmRule, Limit monitor driven by the environment profile's ``alarm_rules`` (NASA-STD-3001, _Window, AlarmRule, A limit on a true (not sensed) module quantity. ``window_s > 0`` evaluates the m, AlarmEvent, ModuleState

### Community 13 - "Typedoc Config"
Cohesion: 0.17
Nodes (11): entryPoints, excludeExternals, excludeInternal, excludePrivate, name, navigation, includeCategories, includeGroups (+3 more)

### Community 14 - "Baseline Physiology"
Cohesion: 0.33
Nodes (7): BaselineModel, BaselineParams, PLACEHOLDER - awaiting review by Luca (bioengineer). Baseline physiology model s, ModuleState, NPCState, StepContext, VitalsUpdate

### Community 15 - "Telemetry Contracts"
Cohesion: 0.36
Nodes (9): VitalsAdapter, VitalsSource, AlarmEvent, GasComposition, HatchState, ModuleState, NPCState, SimulationTick (+1 more)

### Community 16 - "Dashboard Docs & Licensing"
Cohesion: 0.29
Nodes (7): Dashboard (Vite/React), dashboard index.html, Dashboard Vite template README, Third Party Notices, BodyHologram Component, gganatogram GPL-2 anatomy data, VitalsSource and VitalsAdapter Interfaces

### Community 17 - "Lint Config"
Cohesion: 0.33
Nodes (5): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema

### Community 18 - "Layering Test"
Cohesion: 0.50
Nodes (4): _imports(), Path, Layering: plugin authors must be able to work against the SDK alone, and nothing, test_layering()

### Community 19 - "Labelling & Export Format"
Cohesion: 0.67
Nodes (3): Anomaly Labelling (label_row), Chunked Parquet/CSV Export, Output Format (long/wide parquet, manifest)

## Knowledge Gaps
- **105 isolated node(s):** `$schema`, `plugins`, `react/rules-of-hooks`, `react/only-export-components`, `name` (+100 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Engine` connect `CLI & Engine Runner` to `Clock & Alarm Monitor`, `Dataset Export Writers`, `Engine Tick Loop & Constants`, `World Physics & Atmosphere`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Why does `BaseActuator` connect `Clock & Alarm Monitor` to `Life-Support Actuators`, `Dataset Export Writers`, `CLI & Engine Runner`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Why does `ModuleState` connect `Clock & Alarm Monitor` to `Sensors & Metrics`, `Engine Tick Loop & Constants`, `Alarm Rules`, `World Physics & Atmosphere`?**
  _High betweenness centrality (0.044) - this node is a cross-community bridge._
- **Are the 28 inferred relationships involving `ModuleState` (e.g. with `AlarmEvent` and `AlarmRule`) actually correct?**
  _`ModuleState` has 28 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Engine` (e.g. with `_run()` and `_validate()`) actually correct?**
  _`Engine` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `StepContext` (e.g. with `Engine` and `StepResult`) actually correct?**
  _`StepContext` has 27 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Observation` (e.g. with `Engine` and `StepResult`) actually correct?**
  _`Observation` has 25 INFERRED edges - model-reasoned connections that need verification._