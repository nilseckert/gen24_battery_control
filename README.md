# Gen24 Battery Control

Home-Assistant-Integration zur sicheren Steuerung des Batteriespeichers eines
Fronius Gen24 über SunSpec Modbus TCP (Modell 124).

Die Integration stellt nur die **Stellgrößen** bereit. Die Regeln (wann begrenzt
wird) bleiben in Home Assistant, in Automationen und Templates.

## Was sie anders macht

- **Sichere Schreibreihenfolge.** Laut
  [callifo/fronius_modbus#126](https://github.com/callifo/fronius_modbus/issues/126)
  lehnt manche Firmware einen Schreibvorgang ab, der Lade- *und* Entladerate
  gleichzeitig auf 0 % setzt. Die Integration wählt die Reihenfolge so, dass
  dieser Zustand nie als Zwischenschritt entsteht. Als Ziel ist 0 %/0 % erlaubt:
  Ein Symo GEN24 10.0 mit Firmware 1.41.11-1 nimmt ihn an und hält ihn.
  Lehnt ein Gerät ihn ab, meldet die Integration das als „Sollwerte nicht
  übernommen“.
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
| `number` Entladelimit / Entladeleistungslimit | OutWRte (40355) | in % bzw. W der maximalen Leistung |
| `number` Ladelimit / Ladeleistungslimit | InWRte (40356) | in % bzw. W der maximalen Leistung |
| `number` Laden aus dem Netz | OutWRte negativ | W, 0 = aus |
| `number` Entladen ins Netz | InWRte negativ | W, 0 = aus |
| `number` Mindestreserve | MinRsvPct (40350) | % Ladezustand |
| `number` Rückfallzeit | InOutWRte_RvrtTms (40358) | Sekunden, 0 = aus |
| `switch` Netzladen | ChaGriSet (40360) | Laden aus dem Netz erlauben |
| `button` Steuerung zurückgeben | | Modus `auto`, beide Raten 100 % |
| `binary_sensor` Sollwerte nicht übernommen | | Soll ≠ Ist nach allen Versuchen |
| `sensor` Ladezustand, Ladestatus, aktive Werte | | was der Wechselrichter tatsächlich meldet |

Die Adressen gelten für einen Gen24 im Modus *int + SF*. Die Integration sucht
Modell 124 selbst in der SunSpec-Kette. Die Watt-Werte werden über die vom
Wechselrichter gemeldete maximale Ladeleistung (WChaMax) in Prozent umgerechnet.

`select`, `number` und `switch` zeigen den **angeforderten** Wert, die
`sensor`-Entitäten den **tatsächlichen**.

### Laden aus dem Netz und Entladen ins Netz

Der Wechselrichter kennt dafür nur negative Raten. Die Integration trennt das in
eigene Eingaben, damit keine negativen Werte nötig sind:

- **Entladen ins Netz** setzt das Ladelimit auf einen negativen Wert. Die
  Batterie entlädt mit der angegebenen Leistung, was das Haus nicht braucht,
  geht ins Netz. Ladelimit und Ladeleistungslimit zeigen solange 0.
- **Laden aus dem Netz** setzt das Entladelimit auf einen negativen Wert,
  schaltet auf `limit_discharge` und erlaubt Netzladen. Entladelimit und
  Entladeleistungslimit zeigen solange 0.
- 0 beendet den Netzbetrieb, die betroffene Seite geht auf 100 % zurück.
- Die beiden Netzbetriebe schließen sich gegenseitig aus. Ein neues Lade- bzw.
  Entladelimit beendet den Netzbetrieb der jeweiligen Seite.

Getestet an einem Symo GEN24 10.0 mit Firmware 1.41.11-1:

- Entladen ins Netz (negatives InWRte im Modus 3): angenommen, 2000 W stabil.
- Negatives OutWRte im Modus 3: mit ExceptionResponse(3) abgelehnt. Im Modus 2
  angenommen. Ob dabei tatsächlich aus dem Netz geladen wird, ist noch nicht
  belegt (Test bei hohem PV-Überschuss war nicht aussagekräftig).
- Laden 0 % / Entladen 0 %: angenommen und gehalten.

## Optionen

- **Abfrageintervall** (Standard 5 s)
- **Sollwerte erzwingen** (Standard aus): Ist die Option aus, werden Änderungen
  anderer Modbus-Clients als neue Sollwerte übernommen. Ist sie an, werden sie
  überschrieben. Schlägt ein eigener Schreibvorgang fehl, hält die Integration
  den Sollwert in beiden Fällen fest und versucht es weiter.

## Beispiele

Entladung nur bei PV-Defizit:

```yaml
action: gen24_battery_control.set_setpoints
data:
  control_mode: limit_both
  discharge_power_limit: "{{ [states('sensor.hausverbrauch') | float(0) - states('sensor.pv_gesamt') | float(0), 0] | max }}"
  charge_limit: "{{ 0 if is_state('binary_sensor.ladeziel_erreicht', 'on') else 100 }}"
```

Mit 3000 W ins Netz entladen bzw. aus dem Netz laden, und wieder beenden:

```yaml
action: gen24_battery_control.set_setpoints
data:
  grid_discharge_power: 3000   # grid_charge_power: 3000 zum Laden aus dem Netz
```

```yaml
action: gen24_battery_control.set_setpoints
data:
  grid_discharge_power: 0
```

Pro Seite ist nur eine Angabe erlaubt: Entladeseite `discharge_limit` (%),
`discharge_power_limit` (W) oder `grid_charge_power` (W), Ladeseite
`charge_limit` (%), `charge_power_limit` (W) oder `grid_discharge_power` (W).

Soll die Batterie ruhen, setze `discharge_limit: 0` und `charge_limit: 0`.

Automationen, die regelmäßig Lade- und Entladelimit setzen, beenden damit
einen laufenden Netzbetrieb. Solche Automationen sollten pausieren, solange
„Laden aus dem Netz“ oder „Entladen ins Netz“ größer 0 ist.

## Entwicklung

```bash
pip install -r requirements_test.txt
pytest
```

`tests/live_read.py <host>` liest einen echten Wechselrichter nur lesend aus.

## Haftung

Die Integration schreibt Steuerregister des Wechselrichters. Benutzung auf
eigene Gefahr. Siehe [LICENSE](LICENSE).
