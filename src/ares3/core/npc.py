"""NPC as a metabolic state machine: no pathfinding, a daily schedule of (module, activity, MET) blocks."""

from __future__ import annotations

from dataclasses import dataclass, field

from ares3.schemas.crew import ActivityBlock, ActivityClass, CrewMember

from .metabolism import MetabolicRates, rates_for


@dataclass
class NPC:
    spec: CrewMember
    blocks: list[ActivityBlock]
    vitals: dict[str, float] = field(default_factory=dict)
    latent: dict[str, float] = field(default_factory=dict)
    block: ActivityBlock | None = None
    rates: MetabolicRates | None = None
    override: ActivityBlock | None = None  # emergency orders replace the schedule while set

    @classmethod
    def from_spec(cls, spec: CrewMember) -> NPC:
        return cls(spec=spec, blocks=sorted(spec.schedule, key=lambda b: b.from_h))

    @property
    def id(self) -> str:
        return self.spec.id

    def block_at(self, tod_h: float) -> ActivityBlock:
        for b in self.blocks:
            if b.from_h <= tod_h < b.to_h:
                return b
        return self.blocks[-1]  # tod_h == 24.0 can only come from float rounding

    def update(self, tod_h: float, catalog: dict[str, ActivityClass], ref_mass_kg: float) -> None:
        self.block = self.override or self.block_at(tod_h)
        self.rates = rates_for(self.block, catalog, self.spec.body_mass_kg, ref_mass_kg)
