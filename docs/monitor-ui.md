# Monitor: contratto per la UI

La UI non ha logica di soglie: arriva tutto calcolato nel `SimulationTick` (`src/ares3/sdk/types.py` è la fonte di verità; lo
specchio a mano è `dashboard/src/telemetry/types.ts`).

## Stati del sistema (`tick.monitor_mode`)

| Valore | Quando | Banner suggerito |
|---|---|---|
| `passive` | nessuna emergenza aperta | verde, nessuna interruzione |
| `alert` | almeno un'emergenza `suspected`, oppure una `confirmed` di classe `caution`/`advisory` senza playbook | giallo |
| `reaction` | almeno un'emergenza `confirmed` di classe `emergency`/`warning`, o con un playbook in corso | rosso (emergency) o arancio (warning) |

Il modo è il massimo sulle emergenze aperte. Sale subito e scende solo dopo `classifier.mode_hold_s` (60 s) senza il livello
più alto, quindi non sfarfalla. Ogni cambio è un `MonitorEvent` con `kind: "mode_changed"` (`"monitoring: alert -> reaction"`).

## Classe di allerta (`Emergency.alert_class`)

`emergency` rosso, `warning` arancio, `caution` giallo, `advisory` blu. Viene da `classifier.classes` nel YAML del monitor
(chiavi `kind:severity:cause`, `kind:severity` o `kind`; senza voce: critical -> `emergency`, warning -> `warning`).
Livelli ISS: NASA, *CLD HSI Workshop - Alerts* (piano §11 [R1]).

## Ancora da fare (fasi successive del piano)

`Emergency.evidence`, `tick.procedures`, `tick.ml`, il comando `ack_step`, i tipi di azione `power` / `sensor` / `crew`.
Questa nota si aggiorna quando entrano.
