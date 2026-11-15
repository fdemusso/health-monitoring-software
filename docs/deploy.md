# Distribuzione: `ares.daado.dev` + `ares-api.daado.dev`

```
browser ──https──▶ ares.daado.dev       dashboard (file statici su Cloudflare Workers, gratis)
   │
   └────wss─────▶ ares-api.daado.dev    Cloudflare ──tunnel──▶ container `ares3` (ares3 serve) sul Proxmox
```

Il backend non apre nessuna porta sul router: il container `cloudflared` esce verso Cloudflare e il traffico torna dentro quel
tunnel. `.dev` è un dominio solo-HTTPS (HSTS): per questo il socket deve essere `wss://`, ed è quello che dà il tunnel.

## Sicurezza (cosa è attivo)

| Misura | Dove |
|---|---|
| **Token operatore**: chi collega con `?token=<ARES3_TOKEN>` può mandare comandi; gli altri (spettatori) ricevono tutto, i loro comandi sono rifiutati (`read-only connection`) | `ares3 serve --token` / `ARES3_TOKEN` |
| **Visitatori (giudici) senza login**: nessun accesso Cloudflare, nessun token. Vedono tutto in diretta e possono solo `approve_action`, `reject_action` e `ack_step` (partecipare alla risposta); iniettare guasti, `reset`, velocità, pausa e `declare_emergency` richiedono il token. Per sola lettura: `ARES3_GUEST_COMMANDS=` vuoto in `deploy/.env` | `--guest-commands` |
| **Origin**: da un browser il socket si apre solo dalla pagina `https://ares.daado.dev` (403 per le altre) | `--allow-origin` |
| **Velocità massima** chiesta da un client: 200x (altrimenti `set_speed` potrebbe tenere la CPU al 100%) | `--max-speed` |
| **Connessioni**: al massimo 50, messaggi dal client al massimo 64 KB | `--max-clients`, automatico |
| Container non root, filesystem in sola lettura, nessuna capability, 1 GB di RAM e 1,5 CPU | `deploy/docker-compose.yml` |
| Nessuna porta pubblicata: l'unica via d'ingresso è il tunnel | `deploy/docker-compose.yml` |
| Segreti solo in `deploy/.env` (ignorato da git) | `.gitignore` |

Il token del browser sta nel **frammento** dell'indirizzo (`https://ares.daado.dev/#token=...`): un frammento non arriva mai al server
né ai log. Dal browser lo legge `dashboard/src/telemetry/createBackend.ts` e lo aggiunge a `wss://...?token=` (la UI non lo mostra).
Senza token la pagina è per i visitatori: va bene per la giuria (vedi sopra cosa possono fare).

## 1. Tunnel (Cloudflare, nel browser)

1. `dash.cloudflare.com` → **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel** → **Cloudflared** → nome `ares`.
2. Copia il **token** (la stringa lunga dopo `--token`): è il `TUNNEL_TOKEN`.
3. Scheda **Public Hostname** → **Add**: sottodominio `ares-api`, dominio `daado.dev`, servizio **HTTP** `ares3:8765`.
   (I WebSocket passano senza altre opzioni. Il record DNS lo crea Cloudflare.)

## 2. Backend (sul docker host del Proxmox)

```bash
git clone <repo> /opt/stacks/ares3 && cd /opt/stacks/ares3      # oppure copia la cartella: serve tutto tranne output/
cp deploy/.env.example deploy/.env
openssl rand -hex 24                                            # il valore di ARES3_TOKEN
nano deploy/.env                                                # ARES3_TOKEN=... TUNNEL_TOKEN=...
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
docker compose -f deploy/docker-compose.yml logs -f ares3       # "warming up 4 simulated hours ..." poi "serving ..."
```

Il primo avvio richiede circa un minuto in più per il riscaldamento (4 ore simulate: i rilevatori ML ne hanno bisogno di 3 e i grafici
partono già pieni). Alla fine lo stato viene salvato nel volume `ares3-cache` (`--warmup-cache=/cache`): ai riavvii successivi
(crash, `restart`, reboot dell'host) il log dice `warm-up of 4 h restored from /cache (no wait)` e il backend è pronto in pochi secondi.

La cache ha una chiave che comprende codice (`src/ares3`), scenario risolto, modelli `.joblib` e `--warmup-h`: dopo un aggiornamento
(`git pull` + `up -d --build`) la chiave cambia, il primo avvio rifà il riscaldamento e sostituisce il file (resta un solo file).
Uno stato vecchio non viene mai caricato. Se il file è illeggibile si ricomincia da zero, senza errori. È un pickle: il volume deve
restare solo nostro. Per forzare un nuovo riscaldamento: `docker compose -f deploy/docker-compose.yml down && docker volume rm deploy_ares3-cache`
(il nome del volume è `<cartella del compose>_ares3-cache`: controlla con `docker volume ls`).

**Aggiornare un server già in funzione** (prima del merge non ha il volume, dopo sì):

```bash
cd /opt/stacks/ares3 && git pull                                 # porta compose, Dockerfile e codice nuovi
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
docker compose -f deploy/docker-compose.yml logs -f ares3        # 1° avvio: "warming up..." e "warm-up cache written: /cache/warmup-<chiave>.pkl"
docker compose -f deploy/docker-compose.yml restart ares3        # prova: ora "restored from /cache (no wait)"
```

Il Dockerfile cambia (cartella `/cache` di proprietà dell'utente `ares`), quindi serve `--build`; `.env` e il tunnel non cambiano.
Se il compose è gestito da un'interfaccia (Portainer o simili), aggiungere a mano al servizio `ares3` l'argomento
`--warmup-cache=/cache` e il volume nominato `ares3-cache:/cache`, e ricostruire l'immagine.

Prova da un altro computer (non serve la UI):

```bash
uv run python tools/demo_client.py --url wss://ares-api.daado.dev --token <ARES3_TOKEN> --fault none --seconds 5
```

## 3. Dashboard (Cloudflare Workers)

```bash
cd dashboard
pnpm install
VITE_ARES_WS_URL=wss://ares-api.daado.dev pnpm build
npx wrangler login                                   # una volta: apre il browser
npx wrangler deploy -c wrangler.production.jsonc     # pubblica ./dist come Worker `ares-dashboard` E collega il dominio ares.daado.dev
```

`dashboard/wrangler.production.jsonc` dichiara il dominio personalizzato (`routes: ares.daado.dev, custom_domain`): il deploy crea da solo
il record DNS e il certificato. Il `wrangler.jsonc` del team (progetto `body-hologram`, senza dominio) resta com'è per chi pubblica sul
proprio account.

Dopo il deploy controllare che NESSUNA applicazione di Cloudflare Access copra `ares.daado.dev` e `ares-api.daado.dev`
(Zero Trust -> Access controls -> Applications): una applicazione senza policy manda tutti a una pagina di login e il WebSocket
non si collega. Per un hostname pubblico serve una policy `Bypass` per `Everyone`, oppure nessuna applicazione.

Se il browser mostra "Backend unreachable" subito dopo la creazione dei record, e solo su una rete, il resolver DNS di quella rete sta
ancora ricordando "nome inesistente" (TTL negativo fino a 30 minuti): provare da un'altra rete o svuotare la cache del resolver.

La UI deve contenere `dashboard/src/lib/utils.ts` (il `.gitignore` ora lo lascia passare), `types.ts` / `websocket.ts` / `store.ts`
(storia, `ack_step`, ruolo).

Licenza: la UI contiene `anatomy.json` derivato da gganatogram (GPL-2). Pubblicarla la distribuisce: tenere un link ai sorgenti
e `dashboard/LICENSE` / `THIRD_PARTY_NOTICES.md` raggiungibili dal sito.

## 4. Operare

| Cosa | Come |
|---|---|
| Aprire come operatore | `https://ares.daado.dev/#token=<ARES3_TOKEN>` |
| Aprire come visitatore / giudice | `https://ares.daado.dev/` (senza login: guarda e può approvare le richieste e chiudere i passi delle procedure) |
| Iniettare un guasto per la demo | dal pannello debug della UI, o `tools/demo_client.py --fault fire --module COL ...` |
| Riavviare la simulazione da zero | `docker compose -f deploy/docker-compose.yml restart ares3` (con il riscaldamento). Il comando `reset` dalla UI riparte freddo |
| Cambiare token | modificare `deploy/.env` e `docker compose ... up -d` |
| Vedere chi è collegato / errori | `docker compose ... logs ares3` e, per il tunnel, `logs cloudflared` |

## Quanto pesa sul server (misurato)

Misure sul container `docker-host` (i5-9500, 6 core, 8 GB) con un visitatore collegato:

| | CPU | RAM | Rete |
|---|---|---|---|
| `ares3` (backend) | circa 6-7% di un core a 10x | 236 MB (tetto 1 GB) | circa 13 KB per frame, 9 frame/s = 1 Mbit/s per spettatore non compresso; circa 0,6 Mbit/s sul filo |
| `cloudflared` | circa 0,7% | 20 MB | uguale al traffico dei client |
| Avvio (warm-up 4 h simulate) | 1 core per 3-4 minuti, una volta | - | - |

Il server Proxmox resta al 97% libero. Con `--pause-when-idle` (attivo nel compose) la simulazione **si ferma quando non c'è nessuno
collegato** e riparte al primo visitatore: a vuoto non usa CPU. Il tempo simulato non avanza durante la pausa.

Il collo di bottiglia è la **banda in uscita** del collegamento di casa: ogni spettatore costa circa 0,5 Mbit/s a 5 frame/s
(`ARES3_FPS`, predefinito 5) e circa 1 Mbit/s a 10; con `ARES3_MAX_CLIENTS=30` il massimo è circa 15-30 Mbit/s.

## Costi e limiti

Cloudflare Workers (file statici), il Tunnel e il DNS sono gratuiti. Il backend gira su una macchina tua: una simulazione condivisa
da tutti i client (un solo processo, circa 4,4 ms per tick, meno del 10% di un core a 10x). Più spettatori non la rallentano; i
comandi di un operatore valgono per tutti.

Azure: la prova gratuita blocca le dimensioni di VM in tutte le regioni europee controllate (`NotAvailableForSubscription`, quota di
calcolo a zero e non aumentabile). Se si vuole usare comunque, serve passare a pay-as-you-go; il compose di `deploy/` funziona uguale su
qualsiasi macchina con Docker.
