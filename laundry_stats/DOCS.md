# Laundry Stats

Statistik for vaskemaskine og tørretumbler ud fra et smart-stik med effektmåling (Shelly, Tasmota, Zigbee-stik o.l.).
Add-on'et læser stikkenes effekt fra Home Assistants historik, så det kræver ingen ekstra integration.

## Opsætning

Hver maskine er én post under `machines`:

```yaml
machines:
  - name: Vaskemaskine
    type: washer
    power_entity: sensor.vaskemaskine_power
    start_watt: 50
    start_seconds: 0
    stop_watt: 45
    stop_minutes: 4
    min_minutes: 15
    skip_entity: timer.vaskemaskine_afkalkning
  - name: Tørretumbler
    type: dryer
    power_entity: sensor.torretumbler_power
    start_watt: 100
    start_seconds: 60
    stop_watt: 35
    stop_minutes: 2
    min_minutes: 15
```

| Felt | Betydning |
|---|---|
| `type` | `washer` eller `dryer`. Styrer farve, ikon og koblingen mellem vask og tørring. |
| `power_entity` | Stikkets effektsensor i watt. |
| `start_watt`, `start_seconds` | En tur starter, når effekten har været over `start_watt` i `start_seconds` sekunder. Tørretumblerens krølbeskyttelse rykker ca. 30 sek ad gangen, så 60 sek holder den ude. |
| `stop_watt`, `stop_minutes` | En tur er færdig, når effekten har været under `stop_watt` i `stop_minutes` minutter. Vaskemaskinens pauser mellem skyl skal være kortere end `stop_minutes`. Sluttiden er det øjeblik, effekten faldt, ikke når ventetiden er gået. |
| `min_minutes` | Kortere ture (fx et afbrudt program) tælles ikke. |
| `skip_entity` | Valgfri. Ture, der starter, mens den er `on` eller `active`, holdes ude af statistikken, fx afkalkning. |

Find de rigtige niveauer ved at se på stikkets historik i Home Assistant for et par ture. Under **Opsætning** i
add-on'et kan du se de niveauer, der bruges.

### Elpris

Uden `price_entity` regnes med `price_per_kwh`. Med en elpris-sensor (fx `sensor.energi_data_service`) læses
prisens historik for hver tur, og hvert minuts strøm ganges med den pris, der gjaldt da.

### Historik

Første gang læses de seneste `import_days` dage fra Home Assistants historik. Recorderen gemmer som standard
10 dage (`purge_keep_days`). Under **Opsætning → Læs historikken igen** kan den læses igen. Ture, der allerede er
gemt, springes over.

Databasen ligger i `addon_configs/<slug>/laundry_stats.db` og kan tages backup af via Samba.

## Home Assistant

Med `ha_sensors` oprettes sensorer pr. maskine, fx for maskinen `Vaskemaskine`:

| Sensor | Indhold |
|---|---|
| `sensor.laundry_stats_vaskemaskine_status` | `running` / `idle`, med effekt, starttid og forventet færdig som attributter |
| `sensor.laundry_stats_vaskemaskine_expected_finish` | Forventet færdig-tid (tidsstempel) |
| `sensor.laundry_stats_vaskemaskine_cycles_today` / `_cycles_month` | Antal ture |
| `sensor.laundry_stats_vaskemaskine_energy_month` / `_cost_month` | kWh og kr denne måned |
| `sensor.laundry_stats_vaskemaskine_last_cycle` | Sidste tur i minutter |

Når en tur er færdig, sendes eventet `laundry_stats_cycle_finished` med `machine`, `machine_id`, `type`, `minutes`,
`kwh`, `cost` og `started`. Det kan bruges i egne automationer i stedet for `notify_services`:

```yaml
triggers:
  - trigger: event
    event_type: laundry_stats_cycle_finished
    event_data:
      type: washer
actions:
  - action: notify.mobile_app_telefon
    data:
      title: "{{ trigger.event.data.machine }}"
      message: "Færdig efter {{ trigger.event.data.minutes }} min."
```

## Forventet færdig-tid

Hver tur gemmes med sin effekt minut for minut. Mens en maskine kører, sammenlignes forløbet indtil nu med de
seneste 40 ture. De ture, der ligner mest (samme program varmer, holder pause og centrifugerer på samme tid), giver
gættet. De første 5 minutter bruges medianen. Et program skal være kørt én gang, før det kan genkendes. Under
**Indsigt** står det, hvor præcist gættet typisk har været.
