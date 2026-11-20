<p align="center"><img src="assets/logo.png" width="160" alt="Laundry Stats logo"></p>

<h1 align="center">Laundry Stats</h1>

<p align="center"><a href="https://github.com/Tntdruid/laundry-stats/actions/workflows/ci.yaml"><img src="https://github.com/Tntdruid/laundry-stats/actions/workflows/ci.yaml/badge.svg" alt="CI"></a></p>

🇬🇧 [English](#english) · 🇩🇰 [Dansk](#dansk)

---

## English

A Home Assistant add-on with statistics for a washer and a dryer on smart plugs with power metering. It is a sibling of [Jellyfin Video Stats](https://github.com/Tntdruid/jellyfin-video-stats). The add-on's own pages are in Danish.

- Finds cycles in the plugs' power readings, with start and stop levels per machine, so a dryer's anti-crease tumbling and a washer's pauses don't count as new cycles
- Reads the history Home Assistant already has on first start, so the statistics don't start from zero
- Cycles, energy and cost per day, week and month, compared with the previous period; the cost can follow an electricity price sensor minute by minute
- Expected finish time for a running cycle, learnt from earlier cycles with the same power curve
- Pairs each wash with the dryer run after it: share of washes dried and how long the laundry waited
- Heatmap of when you do laundry, cycle lengths, insights and a page per cycle with its power curve
- Home Assistant sensors, an event when a cycle is done and optional notifications
- CSV export (opens directly in Danish Excel)
- Any number of machines

See [laundry_stats/DOCS.md](laundry_stats/DOCS.md) for setup (in Danish).

### Installation in Home Assistant

1. Go to **Settings → Apps → App store → ⋮ → Repositories**.
2. Add `https://github.com/Tntdruid/laundry-stats`.
3. Find **Laundry Stats** in the store and install it.
4. Under **Configuration**, set each machine's `power_entity` and levels, then start the add-on.
5. Open **Vaskestatistik** in the sidebar.

### Local development with demo data

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
curl -L -o laundry_stats/app/static/echarts.min.js https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js
.venv/Scripts/python dev/seed_demo.py
.venv/Scripts/python dev/run_demo.py
```

Then open http://localhost:8099. The demo reads four months of made-up laundry through the real collector from a fake Home Assistant, with a wash running right now. If you set `HA_URL` (e.g. `http://homeassistant.local:8123/api`) and `HA_TOKEN` (a long-lived access token), it reads your real machines instead.

Run the tests with `.venv/Scripts/python -m pytest tests`.

---

## Dansk

Home Assistant-add-on med statistik for vaskemaskine og tørretumbler på smart-stik med effektmåling. Søster til [Jellyfin Video Stats](https://github.com/Tntdruid/jellyfin-video-stats).

- Finder turene i stikkenes effekt med start- og stopniveau pr. maskine, så tørretumblerens krølbeskyttelse og vaskemaskinens pauser ikke tæller som nye ture
- Læser den historik, Home Assistant allerede har, ved første start, så statistikken ikke starter fra nul
- Ture, strøm og pris pr. dag, uge og måned sammenlignet med forrige periode. Prisen kan følge en elpris-sensor minut for minut
- Forventet færdig-tid for en igangværende tur, lært af tidligere ture med samme effektforløb
- Kobler hver vask med tørringen bagefter: andel af vaskene, der tørres, og hvor længe tøjet ventede
- Heatmap over, hvornår der vaskes, turenes længde, indsigt og en side pr. tur med effektkurven
- Sensorer i Home Assistant, et event når en tur er færdig og valgfri notifikationer
- CSV-eksport (åbner direkte i dansk Excel)
- Så mange maskiner, du vil

Se [laundry_stats/DOCS.md](laundry_stats/DOCS.md) for opsætning.
