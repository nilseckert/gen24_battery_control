# Gen24 Battery Control

Home-Assistant-Integration zur sicheren Steuerung des Batteriespeichers eines
Fronius Gen24 über SunSpec Modbus TCP (Modell 124).

Die Integration stellt nur die **Stellgrößen** bereit. Die Regeln (wann begrenzt
wird) bleiben in Home Assistant, in Automationen und Templates.

## Was sie anders macht

- **Sichere Schreibreihenfolge.** Die Gen24-Firmware lehnt jeden Schreibvorgang
  ab, der Lade- *und* Entladerate gleichzeitig auf 0 % setzt. Die Integration
  wählt die Reihenfolge so, dass dieser Zwischenzustand nie entsteht
  (vgl. [callifo/fronius_modbus#126](https://github.com/callifo/fronius_modbus/issues/126)).
- **Prüfung statt Annahme.** Nach jedem Schreiben wird der Block zurückgelesen.
  Übernimmt der Wechselrichter die Werte nicht, wird wiederholt, eine Reparatur-
  meldung erzeugt und `binary_sensor.…_sollwerte_nicht_ubernommen` eingeschaltet
  (vgl. [#127](https://github.com/callifo/fronius_modbus/issues/127)).
- **Watchdog.** Solange ein begrenzender Modus aktiv ist, werden die Raten vor
  Ablauf der Rückfallzeit (`InOutWRte_RvrtTms`) erneut geschrieben. Fällt Home
  Assistant aus, kehrt der Wechselrichter nach der Rückfallzeit selbst in den
  Automatikbetrieb zurück.
- **Nur Änderungen werden geschrieben.** Unveränderte Werte erzeugen keinen
  Modbus-Verkehr (außer dem Watchdog).
- **Mehrere Werte atomar.** Der Service `gen24_battery_control.set_setpoints`
  setzt Modus und beide Raten in einem geprüften Schritt.

## Voraussetzungen

Im Webinterface des Wechselrichters unter *Kommunikation → Modbus*:

- Modbus TCP (Slave) aktiviert, Port 502
- SunSpec Model Type: **int + SF**
- Wechselrichter-Steuerung über Modbus erlaubt

Die Integration öffnet eine eigene Modbus-Verbindung. Der Gen24 erlaubt nur
wenige gleichzeitige Verbindungen. Andere Clients, die dieselben Register
schreiben (z. B. evcc mit Batteriesteuerung oder alte HA-Scripts), sollten
abgeschaltet werden.

## Installation

HACS → Integrationen → ⋮ → Benutzerdefinierte Repositories →
`https://github.com/nilseckert/gen24_battery_control` (Kategorie Integration).
Danach *Einstellungen → Geräte & Dienste → Integration hinzufügen →
Gen24 Battery Control*.

## Entitäten

| Entität | Register | Bedeutung |
|---|---|---|
| `select` Steuermodus | StorCtl_Mod (40348) | `auto`, `limit_charge`, `limit_discharge`, `limit_both` |
| `number` Entladelimit | OutWRte (40355) | % der maximalen Leistung, negativ = erzwungenes Laden |
| `number` Ladelimit | InWRte (40356) | % der maximalen Leistung, negativ = erzwungenes Entladen |
| `number` Entladeleistungslimit | OutWRte (40355) | dasselbe in kW, umgerechnet über WChaMax |
| `number` Ladeleistungslimit | InWRte (40356) | dasselbe in kW, umgerechnet über WChaMax |
| `number` Mindestreserve | MinRsvPct (40350) | % Ladezustand |
| `number` Rückfallzeit | InOutWRte_RvrtTms (40358) | Sekunden, 0 = aus |
| `switch` Netzladen | ChaGriSet (40360) | Laden aus dem Netz erlauben |
| `button` Steuerung zurückgeben | | Modus `auto`, beide Raten 100 % |
| `binary_sensor` Sollwerte nicht übernommen | | Soll ≠ Ist nach allen Versuchen |
| `sensor` Ladezustand, Ladestatus, aktive Werte | | was der Wechselrichter tatsächlich meldet |

Die Adressen gelten für einen Gen24 im Modus *int + SF*. Die Integration sucht
Modell 124 selbst in der SunSpec-Kette.

`select`, `number` und `switch` zeigen den **angeforderten** Wert, die
`sensor`-Entitäten den **tatsächlichen**.

## Optionen

- **Abfrageintervall** (Standard 5 s)
- **Sollwerte erzwingen** (Standard aus): Ist die Option aus, werden Änderungen
  anderer Modbus-Clients als neue Sollwerte übernommen. Ist sie an, werden sie
  überschrieben. Schlägt ein eigener Schreibvorgang fehl, hält die Integration
  den Sollwert in beiden Fällen fest und versucht es weiter.

## Beispiel: Entladung nur bei PV-Defizit

```yaml
automation:
  - alias: Batteriesteuerung
    triggers:
      - trigger: time_pattern
        seconds: "/10"
    actions:
      - action: gen24_battery_control.set_setpoints
        data:
          control_mode: limit_both
          discharge_limit: >
            {% set defizit = [states('sensor.hausverbrauch') | float(0)
                              - states('sensor.pv_gesamt') | float(0), 0] | max %}
            {{ [defizit / states('sensor.symo_gen24_10_0_maximale_ladeleistung') | float(1) * 100, 100] | min }}
          charge_limit: "{{ 0 if is_state('binary_sensor.ladeziel_erreicht', 'on') else 100 }}"
```

Statt in Prozent lassen sich die Limits auch in kW angeben
(`discharge_power_limit`, `charge_power_limit`). Pro Richtung ist nur eine der
beiden Angaben erlaubt. Die kW-Werte werden in Prozent der vom Wechselrichter
gemeldeten maximalen Ladeleistung (WChaMax) umgerechnet:

```yaml
action: gen24_battery_control.set_setpoints
data:
  control_mode: limit_both
  discharge_power_limit: "{{ [states('sensor.hausverbrauch') | float(0) / 1000 - states('sensor.pv_gesamt') | float(0) / 1000, 0.1] | max }}"
  charge_power_limit: 0
```

Achtung: `discharge_limit: 0` zusammen mit `charge_limit: 0` wird abgelehnt.
Soll die Batterie ruhen, genügt ein kleiner Wert, z. B. `discharge_limit: 1`.

## Entwicklung

```bash
pip install -r requirements_test.txt
pytest
```

`tests/live_read.py <host>` liest einen echten Wechselrichter nur lesend aus.

## Haftung

Die Integration schreibt Steuerregister des Wechselrichters. Benutzung auf
eigene Gefahr. Siehe [LICENSE](LICENSE).
