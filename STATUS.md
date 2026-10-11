# STATUS — bitácora de decisiones

## Fase 0 — Cimientos y spikes (en curso)

### Hecho
- Entorno: uv, Python 3.12, AWS CLI (v1 vía uv tool) instalados.
- Repo `doorledger` (monorepo uv). Licencia Apache-2.0.
- **SDK `ringpartner`** completo: cliente REST sync/async, WHEP (aiortc), webhooks (verificación HMAC), simulador de webhooks firmado, record/replay de fixtures, CLI. 55 tests verdes, ruff limpio, wheel construido. 7 bugs corregidos por el agente revisor (incluye fuga de `security_token` en mensajes de error).
- Core: `domain`, `exposure` (modelo térmico Newton), `porch` (tracker k-de-n), `ledger` (SQLite), `reconcile` (esperado vs. observado), `weather` (Open-Meteo), `vision` (Bedrock Converse + stub). Prueba de humo OK: detecta llegada tarde, visita corta, insulina comprometida.

### Spikes
| Spike | Estado | Notas |
|---|---|---|
| S1 Playground | ✅ | Dispositivo "Playground Device" online, no cifrado. Fixtures grabados (devices, status, capabilities, configurations, location, history, users/me redactado). Snapshot funciona con `at=` = inicio de un evento del historial (rango "latest_in_range" da 403). |
| S2 WHEP servidor | ✅ | aiortc → H264 1280x720, ~4 fps efectivos. Escena se elige en la UI del Playground (Package/Vehicle/Motion) y aplica también a sesiones del servidor. 500 si se abre otra sesión antes de que cierre la anterior → reintento con espera de 20 s. MediaRecorder MP4 no finaliza (moov) → usamos frames + cv2.VideoWriter. Clip de paquete: "Thief stealing our package" (YouTube, CC BY 4.0) → ATRIBUIR en video y README. |
| S3 Bedrock | ⏳ AWS conectado (IAM `doorledger-dev`, us-east-1); Bedrock responde *AccessDenied: account being verified* (<2 h) | Modelos visibles: Nova Lite/Pro/2-Lite, Claude Haiku 4.5/5.5, Sonnet 4.6/5.5, Opus 5.5. Comparar Nova Lite vs Haiku 4.5 en frames |
| S4 Código de presencia | 🟡 AJUSTADO | Sintético: 100% a 30–50 cm, 0% a 1 m (QR del teléfono <2 px/módulo). Decisión: instrucción a la cuidadora "30–50 cm, 2–3 s quieta", código compacto de 25 dígitos (QR mínimo, EC M), leer cada 2–3 frames, mantener código de 6 dígitos como respaldo leído por visión. Falta validar con footage real (IR nocturno, watermark). |
| S5 Strands | pendiente | |
| S6 Notificaciones | pendiente | |

### Decisiones
- **G-S4:** el criterio "≥95% a 1 m" no se cumple → se ajusta el CÓMO (distancia 30–50 cm + código compacto + respaldo de 6 dígitos), no el alcance.
- Insulina: no hay límite de minutos sobre 8 °C (aguanta semanas a temperatura ambiente); el riesgo real es superar ~30 °C. Perfiles más estrictos (biológicos) usan `max_minutes_above_store`.
- Reconciliación determinista; el LLM solo decide acciones y redacta. El LLM nunca decide si una visita ocurrió.

### Necesito de Brandon
- ✅ AWS listo: plan Paid, presupuesto US$30/mes con alertas al correo, usuario IAM con permisos mínimos.
- Token del Playground de Ring.
