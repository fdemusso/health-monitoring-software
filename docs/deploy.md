# Deployment: `ares.daado.dev` + `ares-api.daado.dev`

```
browser ──https──▶ ares.daado.dev       dashboard (static files on Cloudflare Workers, free)
   │
   └────wss─────▶ ares-api.daado.dev    Cloudflare ──tunnel──▶ `ares3` container (ares3 serve) on the Proxmox
```

The backend opens no port on the router: the `cloudflared` container connects out to Cloudflare and the traffic comes back in through that
tunnel. `.dev` is an HTTPS-only domain (HSTS): that is why the socket must be `wss://`, which is what the tunnel provides.

## Security (what is active)

| Measure | Where |
|---|---|
| **Operator token**: whoever connects with `?token=<ARES3_TOKEN>` can send commands; the others (viewers) receive everything, their commands are rejected (`read-only connection`) | `ares3 serve --token` / `ARES3_TOKEN` |
| **Visitors (judges) without login**: no Cloudflare access, no token. They see everything live and may only `approve_action`, `reject_action`, `ack_step` (take part in the response) and `inject_event` / `stop_event` (the scenarios menu); `reset`, speed, pause and `declare_emergency` need the token. For read-only: empty `ARES3_GUEST_COMMANDS=` in `deploy/.env` | `--guest-commands` |
| **Origin**: from a browser the socket opens only from the page `https://ares.daado.dev` (403 for the others) | `--allow-origin` |
| **Maximum speed** a client may ask for: 60x (otherwise `set_speed` could keep the CPU at 100%) | `--max-speed` |
| **Connections**: at most 8 (`ARES3_MAX_CLIENTS`), client messages at most 64 KB | `--max-clients`, automatic |
| Non-root container, read-only filesystem, no capabilities, 1 GB of RAM and 1.5 CPU | `deploy/docker-compose.yml` |
| No published port: the only way in is the tunnel | `deploy/docker-compose.yml` |
| Secrets only in `deploy/.env` (ignored by git) | `.gitignore` |

The browser token lives in the address **fragment** (`https://ares.daado.dev/#token=...`): a fragment never reaches the server
or the logs. In the browser it is read by `dashboard/src/telemetry/createBackend.ts` and appended to `wss://...?token=` (the UI does not show it).
Without a token the page is for visitors: fine for the jury (see above for what they can do).

## 1. Tunnel (Cloudflare, in the browser)

1. `dash.cloudflare.com` → **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel** → **Cloudflared** → name `ares`.
2. Copy the **token** (the long string after `--token`): it is the `TUNNEL_TOKEN`.
3. **Public Hostname** tab → **Add**: subdomain `ares-api`, domain `daado.dev`, service **HTTP** `ares3:8765`.
   (WebSockets pass without any other option. Cloudflare creates the DNS record.)

## 2. Backend (on the Proxmox docker host)

```bash
git clone <repo> /opt/stacks/ares3 && cd /opt/stacks/ares3      # or copy the folder: everything except output/ is needed
cp deploy/.env.example deploy/.env
openssl rand -hex 24                                            # the value of ARES3_TOKEN
nano deploy/.env                                                # ARES3_TOKEN=... TUNNEL_TOKEN=...
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
docker compose -f deploy/docker-compose.yml logs -f ares3       # "warming up 4 simulated hours ..." then "serving ..."
```

The first start takes about a minute longer for the warm-up (4 simulated hours: the ML detectors need 3 and the charts
start already full). At the end the state is saved in the `ares3-cache` volume (`--warmup-cache=/cache`): on later restarts
(crash, `restart`, host reboot) the log says `warm-up of 4 h restored from /cache (no wait)` and the backend is ready in a few seconds.

The cache has a key made of the code (`src/ares3`), the resolved scenario, the `.joblib` models and `--warmup-h`: after an update
(`git pull` + `up -d --build`) the key changes, the first start redoes the warm-up and replaces the file (only one file is kept).
An old state is never loaded. If the file is unreadable it starts over, without errors. It is a pickle: the volume must
stay ours alone. To force a new warm-up: `docker compose -f deploy/docker-compose.yml down && docker volume rm deploy_ares3-cache`
(the volume name is `<compose folder>_ares3-cache`: check with `docker volume ls`).

**Updating a server that is already running** (before the merge it has no volume, after it does):

```bash
cd /opt/stacks/ares3 && git pull                                 # brings the new compose, Dockerfile and code
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
docker compose -f deploy/docker-compose.yml logs -f ares3        # 1st start: "warming up..." and "warm-up cache written: /cache/warmup-<key>.pkl"
docker compose -f deploy/docker-compose.yml restart ares3        # test: now "restored from /cache (no wait)"
```

The Dockerfile changes (`/cache` folder owned by the `ares` user), so `--build` is needed; `.env` and the tunnel do not change.
If the compose is managed through an interface (Portainer or similar), add by hand to the `ares3` service the argument
`--warmup-cache=/cache` and the named volume `ares3-cache:/cache`, and rebuild the image.

Test from another computer (no UI needed):

```bash
uv run python tools/demo_client.py --url wss://ares-api.daado.dev --token <ARES3_TOKEN> --fault none --seconds 5
```

## 3. Dashboard (Cloudflare Workers)

```bash
cd dashboard
pnpm install
VITE_ARES_WS_URL=wss://ares-api.daado.dev pnpm build
npx wrangler login                                   # once: opens the browser
npx wrangler deploy -c wrangler.production.jsonc     # publishes ./dist as the `ares-dashboard` Worker AND attaches the domain ares.daado.dev
```

`dashboard/wrangler.production.jsonc` declares the custom domain (`routes: ares.daado.dev, custom_domain`): the deploy creates the DNS record
and the certificate by itself. The team's `wrangler.jsonc` (project `body-hologram`, no domain) stays as it is for whoever publishes on their
own account.

After the deploy check that NO Cloudflare Access application covers `ares.daado.dev` and `ares-api.daado.dev`
(Zero Trust -> Access controls -> Applications): an application without a policy sends everyone to a login page and the WebSocket
cannot connect. For a public hostname you need a `Bypass` policy for `Everyone`, or no application at all.

If the browser shows "Backend unreachable" right after the records are created, and only on one network, that network's DNS resolver is
still remembering "no such name" (negative TTL of up to 30 minutes): try from another network or flush the resolver cache.

The UI must contain `dashboard/src/lib/utils.ts` (the `.gitignore` now lets it through), `types.ts` / `websocket.ts` / `store.ts`
(history, `ack_step`, role).

Licence: the UI contains `anatomy.json` derived from gganatogram (GPL-2). Publishing it distributes it: keep a link to the sources
and keep `dashboard/LICENSE` / `THIRD_PARTY_NOTICES.md` reachable from the site.

## 4. Operating

| What | How |
|---|---|
| Open as operator | `https://ares.daado.dev/#token=<ARES3_TOKEN>` |
| Open as visitor / judge | `https://ares.daado.dev/` (no login: they watch, can approve requests, close procedure steps and use the scenarios menu) |
| Inject a fault for the demo | from the UI's Scenarios menu, or `tools/demo_client.py --fault fire --module COL ...` |
| Restart the simulation from zero | `docker compose -f deploy/docker-compose.yml restart ares3` (with the warm-up). The `reset` command from the UI restarts cold |
| Change the token | edit `deploy/.env` and `docker compose ... up -d` |
| See who is connected / errors | `docker compose ... logs ares3` and, for the tunnel, `logs cloudflared` |

## Load on the server (measured)

Measured on the `docker-host` container (i5-9500, 6 cores, 8 GB) with one visitor connected:

| | CPU | RAM | Network |
|---|---|---|---|
| `ares3` (backend) | about 6-7% of a core at 10x | 236 MB (cap 1 GB) | about 13 KB per frame, 9 frames/s = 1 Mbit/s per viewer uncompressed; about 0.6 Mbit/s on the wire |
| `cloudflared` | about 0.7% | 20 MB | same as the clients' traffic |
| Start (4 simulated h warm-up) | 1 core for 3-4 minutes, once | - | - |

The Proxmox server stays 97% free. With `--pause-when-idle` (on in the compose) the simulation **stops when nobody is
connected** and resumes with the first visitor: idle, it uses no CPU. Simulated time does not advance during the pause.

The bottleneck is the home connection's **upload bandwidth**: each viewer costs about 0.5 Mbit/s at 5 frames/s
(`ARES3_FPS`, default 5) and about 1 Mbit/s at 10; with `ARES3_MAX_CLIENTS=8` the maximum is about 15-30 Mbit/s.

## Costs and limits

Cloudflare Workers (static files), the Tunnel and DNS are free. The backend runs on a machine of yours: one simulation shared
by all clients (a single process, about 4.4 ms per tick, under 10% of a core at 10x). More viewers do not slow it down; an operator's
commands apply to everyone.

Azure: the free trial blocks VM sizes in all the European regions checked (`NotAvailableForSubscription`, compute quota at
zero and not increasable). If you want to use it anyway, you need to switch to pay-as-you-go; the compose in `deploy/` works the same on
any machine with Docker.
