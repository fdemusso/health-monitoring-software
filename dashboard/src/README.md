# Dashboard: where things live

Rule: `app/` is the frame around the pages, `features/` are the pages and their dialogs, everything else is shared.
Dependencies point down: `app` -> `features` -> `components` / `domain` / `lib` -> `telemetry`.

| I want to change... | Open |
|---|---|
| Page order, which dialogs exist, landmarks (`header` / `main` / `nav`) | `app/Shell.tsx` |
| Open/close state of pages and dialogs, toast | `app/ui-context.tsx` |
| Top bar (crew pills, clock, theme, link) | `app/shell/` (`CrewStrip`, `CrewPill`, `LinkStatus`, `ThemeToggle`) |
| Backend-down banner, page dots, swipe between pages | `app/shell/` (`ConnectionBanner`, `Pager`, `PageSwiper`) |
| Corner honeycomb menu | `app/nav/` (`HoneycombNav`, `hexGeometry`) |
| Red vignette, toast, "rotate your device" | `app/feedback.tsx` |
| **Status page**: alert banner, environment tiles, vitals chart, alert list, crew activity | `features/status/` (`StatusPage` composes the rest) |
| Alarm list rows (shared by the page, the dialog and the menu) | `features/status/alertRows.tsx` |
| **Crew page**: overview cards; **crew detail popover** (clinical picture, hologram, heart, effort, response), opened from the header pills or a card | `features/crew/` (`CrewPage`, `CrewColumn`, `CrewDetailDialog`, `CrewDetail`, `ResponsePanel`) |
| Action the monitor asks to confirm (popover and card) | `features/crew/PendingPopover.tsx`, `PendingActionCard.tsx`, `pendingKinds.ts` |
| Procedures (the protocol of an emergency, live checklist, library) | `features/crew/ProcedureView.tsx`, `ProtocolsDialog.tsx`, `domain/procedures.ts` |
| Module map dialog | `features/modules/ModulesDialog.tsx` |
| Event history sheet | `features/log/EventLogSheet.tsx` |
| Scenario menu / cheat menu (dev, or `?debug`): speed 1-60x, station and crew events, alarms | `features/debug/` |
| Buttons, dialog, sheet, badges (shadcn on Radix) | `components/ui/` |
| Small shared pieces: chips, status dot, sparkline, brackets | `components/` |
| The 3D-ish body hologram | `components/BodyHologram/` |
| Colours, fonts, tokens, animations | `index.css` |
| Thresholds, status colours, unit conversions, text labels | `domain/` (`limits`, `status`, `units`, `emergencyText`, `crewConfig`) |
| Hooks used by more than one feature (drag, element size) | `lib/` |
| What the backend sends, the store, `useTick()` and friends | `telemetry/` (`types.ts` mirrors `src/ares3/sdk/types.py` by hand) |
| Hologram test page | `dev/HologramHarness.tsx` (`?harness`) |

## Markup rules

- One `h1` per page, and it is the screen-reader-only one in `PageSwiper`; visible titles are `h2` and below.
- A clickable card is an `article` whose title holds a `button` stretched with `after:absolute after:inset-0`. Never put block elements inside a `button`.
- Repeated things (crew, modules, alerts, tiles) are `ul`/`li`; a grid of cards uses `li.contents` so the grid stays one level.
- The page that is not showing is `inert`; closed menu cells are `inert`.
- Status is never colour alone: a `StatusDot` carries its label, a `StatusBadge` has text.
- Everything the user reads is English.

## Housekeeping

- `pnpm knip`: unused files, exports and dependencies. The types in `telemetry/` are kept on purpose (hand-kept mirror of the Python contract, see `knip.json`).
- `pnpm lint` (oxlint) and `pnpm build` (tsc + vite) must stay clean before a commit.
