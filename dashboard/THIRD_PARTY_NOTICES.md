# Third-party notices

## Anatomical silhouette & organ coordinates

The paths in `src/data/anatomy.json` (body outline and organ shapes for
`heart`, `lungs`, `brain`, `liver`, `kidneys`, `stomach`) are extracted and
adapted from:

- Project: [gganatogram](https://github.com/jespermaag/gganatogram) by Jesper Maag
- Source files: `data-raw/homo_sapiens.male_coords.tsv` and
  `data-raw/homo_sapiens.female_coords.tsv`
- License: GPL-2

Only the human ("Homo sapiens") outline and the six organs listed above were
kept; all other species, cell-level data, and unused tissue paths were
discarded. Coordinates were reformatted from TSV rows into JSON
(`{ d, transform }` per path) for use as React/SVG elements — no geometry was
redrawn or altered.

Because this data is derived from a GPL-2 licensed work, this project is
distributed under the GNU General Public License v2 (this `dashboard/` folder) — see
[`LICENSE`](./LICENSE). If you need a non-GPL license, replace
`dashboard/src/data/anatomy.json` and `anatomy.ts` with your own
silhouette/organ artwork first.

## UI stack

- [Tailwind CSS](https://tailwindcss.com) and `tw-animate-css` (MIT)
- shadcn/ui conventions (MIT): `src/components/ui/*` follow its look and `cva` pattern
- `class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react` (MIT / ISC)
- `@fontsource-variable/inter` (Inter typeface, SIL Open Font License 1.1)
