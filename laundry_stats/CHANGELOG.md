# Changelog

🇬🇧 English first, 🇩🇰 dansk nedenunder i hver version.

## 0.1.0

🇬🇧
- First version: statistics for a washer and a dryer on smart plugs with power metering.
- Cycles are found in the plugs' power readings from Home Assistant's history, with a start and stop level per machine. A dryer's anti-crease tumbling and a washer's pauses and ticking after spinning don't count as new cycles.
- The first start reads the history Home Assistant still has, so the statistics don't start from zero. A restart loses nothing.
- Cycles, energy and cost per day, week and month, compared with the previous period. The price can come from an electricity price sensor, minute by minute.
- Expected finish time for a running cycle, learnt from earlier cycles with the same power curve (the same program).
- Pairs washes with the dryer run that followed: share of washes dried, and how long the laundry waited.
- A heatmap of when you do laundry, cycle lengths, insights and a page per cycle with its power curve.
- Sensors in Home Assistant, the event `laundry_stats_cycle_finished` and optional notifications.
- CSV export (opens directly in Danish Excel).

🇩🇰
- Første version: statistik for vaskemaskine og tørretumbler på smart-stik med effektmåling.
- Turene findes i stikkenes effekt fra Home Assistants historik, med et start- og stopniveau pr. maskine. Tørretumblerens krølbeskyttelse og vaskemaskinens pauser og tikken efter centrifugering tæller ikke som nye ture.
- Første start læser den historik, Home Assistant stadig har, så statistikken ikke starter fra nul. En genstart mister ingenting.
- Ture, strøm og pris pr. dag, uge og måned sammenlignet med forrige periode. Prisen kan komme fra en elpris-sensor, minut for minut.
- Forventet færdig-tid for en igangværende tur, lært af tidligere ture med samme effektforløb (samme program).
- Kobler vaske med tørringen bagefter: andel af vaskene, der tørres, og hvor længe tøjet ventede.
- Heatmap over, hvornår der vaskes, turenes længde, indsigt og en side pr. tur med effektkurven.
- Sensorer i Home Assistant, eventet `laundry_stats_cycle_finished` og valgfri notifikationer.
- CSV-eksport (åbner direkte i dansk Excel).
