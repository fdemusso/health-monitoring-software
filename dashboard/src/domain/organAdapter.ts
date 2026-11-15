import { vitalSeverity } from '@/components/BodyHologram/vitals'
import type { VitalsAdapter } from '@/telemetry'
import type { OrganVitals } from '@/types/anatomy'
import { VITAL } from './vitalKeys'


/** SpO2 -> brain severity. ESTIMATE (mapping decision belongs to Luca). */
const SPO2_RANGE = { criticalLow: 85, low: 95, normalHigh: 100, warningHigh: 101, criticalHigh: 102 }

/** Maps engine signals onto the hologram organs. Nothing is invented for liver/kidneys/stomach. */
export const organAdapter: VitalsAdapter = {
  toOrganVitals(npc): OrganVitals {
    const spo2 = npc.vitals[VITAL.spo2]
    return {
      heart: npc.vitals[VITAL.hr],
      lungs: npc.vitals[VITAL.resp],
      brain: spo2 == null ? 0 : vitalSeverity(spo2, SPO2_RANGE),
      liver: 0,
      kidneys: 0,
      stomach: 0,
    }
  },
}
