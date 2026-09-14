# Canonical SOMPO ESP prototype

The authoritative supplied source is
[`firmware/sompo_esp_prototype/sompo_esp_prototype.ino`](../firmware/sompo_esp_prototype/sompo_esp_prototype.ino).
Its 4,668 bytes, including CRLF line endings, were extracted directly from the
request, without edits. SHA-256:
`0cb22569078b6b7bcca6327abec0a8eeb0fd0bd6c1d686684a47616bf755a825`.
The targeted `.gitattributes` entry prevents Git newline conversion. The hash
test protects this source; it does not compile a corrected substitute.

## Physical compatibility boundary

This exact text **cannot compile as supplied**: examples include `constfloat`,
`unsignedlong`, `voidsetup`, and `#define DHT_PIN4` while using `DHT_PIN`.
No tokens, pins, thresholds, timing, buzzer or LCD behavior have been corrected.
It also has **no measurement transport**: no Wi-Fi, HTTP, MQTT or successful
measurement serial output. Its only serial message reports a DHT error. An
ordinary USB serial bridge cannot recover the sensor variables from that output.
LDR is read internally but is not displayed or transmitted.

Therefore there is no claim of a working flash/upload or live end-to-end ESP
connection. The adapter below prepares ingestion for an external acquisition
bridge that can supply genuinely observed values. Building that acquisition
path requires compatible hardware/debug instrumentation and remains unresolved;
the adapter does not guess readings from elapsed time, LCD status or thresholds.
Do not send the test fixtures as physical telemetry.

Existing `firmware/esp32.ino`, `firmware/esp32.example.ino`, `firmware/src/main.cpp`
and `platformio.ini` remain legacy implementations/build targets. They are not
the canonical prototype and were not replaced or redirected to invalid code.
Existing DHT/Wi-Fi preparation instructions apply only to those legacy targets.

## Backend connection

```text
external acquisition bridge (not yet available for this exact source)
  -> POST /dados {deviceId, readingId, observedAt, prototype: {...}}
  -> existing device authentication / rate limit / device-to-machine-to-property identity
  -> services/esp_prototype_adapter.py
  -> existing telemetry persistence, history and machine snapshot
```

Use the existing device provisioning API to associate an active device with an
existing machine/property. The bridge supplies `X-Device-Token` (or
`Authorization: Device ...`) outside source control. No new credentials or
network service are committed. Use an authenticated, encrypted connection when
the bridge runs outside a trusted local network.

The JSON body uses the existing identity envelope and an exclusive `prototype`
object. Do not mix it with `measurements` or legacy top-level DHT fields.

| Prototype field | Requirement / persisted representation |
| --- | --- |
| `temperatura` | Finite Celsius number, required when DHT is valid; numeric measurement with `scope=unknown` |
| `umidade` | Finite percentage 0–100, required when DHT is valid; `scope=unknown` |
| `ventoKmh` | Required finite 0–100 km/h; `scope=other`, target `potentiometer_simulated_wind` |
| `leituraLdrDigital` | Optional integer 0/1, raw digital signal, `scope=unknown`, unit `unknown`; no lux or light/dark polarity inferred |
| `statusGeral` | Required `NORMAL`, `ATENCAO` or `RISCO`; stored verbatim in `deviceLocal`, outside measurements |
| `dhtComErro` | Required boolean; when true omit DHT numbers or supply null, because firmware retains stale values on failure |

Numeric sensor IDs retain the prototype field names. These conservative scopes
avoid claiming an installation context that the source does not establish.
Existing machine sensor profiles using the same IDs must match these descriptors;
conflicts are rejected so an internal-temperature profile cannot reinterpret
prototype measurements. Configure profiles only with their actual semantics.

Local status is never recalculated, translated to backend risk levels, used as a
machine sensor, or used to trigger alerts/Telegram. A local `NORMAL` can coexist
with a DHT error; it does not establish sensor health. The potentiometer is a
simulated wind input, not a meteorological measurement.

`deviceLocal` also records firmware identity, DHT error and the simulated wind
source. It participates in the existing payload hash: a changed local status
with the same `readingId` is a conflict, while an identical retry deduplicates.
Use a stable reading ID and observation timestamp per acquired sample/retry.
If no observation timestamp is supplied, the existing server receipt-time
semantics apply; no acquisition timestamp is invented.

Telemetry history (`GET /fazendas/{id}/maquinas/{id}/telemetria`) includes the
stored `measurements`, `measurementDescriptors` and `deviceLocal`. Machine
snapshots additionally retain `latestDeviceLocal` alongside `latestTelemetryAt`;
a subsequent non-prototype reading clears that latest local-status field.
The backend environmental, machine and operational engines remain authoritative
and unchanged. No presentation snapshot, portfolio, UI telemetry or notification
behavior was changed.

## Verification

`python -m unittest discover -s tests -v` includes contract validation,
authentication, canonical byte integrity, DHT failure, local-status idempotency,
conservative sensor semantics and preservation of the existing machine risk.
All endpoint test writes use mocks; no device, Firebase or Telegram is contacted.
