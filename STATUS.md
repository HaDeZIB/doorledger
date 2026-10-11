# STATUS — bitácora de decisiones

## AgentCore ✅ DESPLEGADO (11-oct 5:25 pm)
Stack `AgentCore-DoorLedgerAgent-dev`, runtime `DoorLedgerAgent_CareAgent-*` (us-east-1). `/api/ask` → AgentCore (Claude Haiku 4.5), ~7.6 s, 5/5 pruebas vivas. ARN en `.env` (no en git). Pipeline AWS: Bedrock (Nova 2 Lite visión + Claude Haiku mensajes) + Strands + AgentCore Runtime + DynamoDB + SNS (pendiente número).

## Sesión 2 (11-oct tarde) — después de la revisión externa #1 (6.9/10)
- ✅ Claude Haiku 4.5 / Sonnet 4.6 activos en Bedrock (Haiku 5.5 "not available for this account").
- ✅ Mensajes bilingües (Rosa en español), caras pixeladas ANTES de Bedrock, solo se guarda el cuadro del evento, retención 30 días.
- ✅ Visión con compuerta de movimiento (−38% a −60% llamadas). Modo ráfaga al tocar el timbre (presence en cada cuadro, 12 s). Poller del historial de Ring + snapshots.
- ✅ PDF de exposición para farmacia. Pase de cuidadora solo con token de agencia.
- ✅ Pipeline de footage propio listo (ingest + verificación de códigos al reproducir). Bug crítico corregido: visit_id debe ser [A-Z0-9-].
- ✅ README raíz, arquitectura (5 diagramas Mermaid), LICENSE/NOTICE, CI, Makefile.
- ✅ DynamoDB `doorledger-ledger` en vivo (mirror). AgentCore empaquetado y probado local; despliegue bloqueado por IAM → pasos para Brandon en deploy/agentcore/README.md.
- ✅ +132 pruebas del motor → 239 passed; 4 bugs reales encontrados y corregidos.
- Higiene: .claude/ y clips sin licencia (Vehicle/Motion) fuera de git; id de cuenta redactado. **Al publicar: historial limpio (orphan) porque commits viejos los contienen.**
- Historia del demo: invierno/Chicago; clip de vehículo (primavera) retirado.

### Pendientes de Brandon
1. Grabar 4 escenas (docs/SHOT_LIST.md). 2. Permisos AgentCore (bootstrap CDK + BedrockAgentCoreFullAccess + inline). 3. Verificar número en SNS sandbox (SMS reales). 4. Aprobar publicación (GitHub, PyPI, Vercel). 5. Crédito exacto del clip CC BY.

## Gate G1 — ✅ VERDE (11-oct)
S1, S2, S3, S5 pasaron; S4 ajustado (30–50 cm + código compacto + respaldo 6 dígitos); S6 pendiente de bot de Telegram (no bloquea: el dashboard muestra las acciones). Arquitectura congelada: Ring WHEP → Watcher (Nova 2 Lite + lector de códigos) → PorchTracker → Engine (reconcile determinista) → Responder (guardrails + Writer Bedrock) → Ledger → API/SSE → Dashboard; CareAgent (Strands) para Q&A y resumen.

## Fase 1 — Medicina en el porche: casi completa
- ✅ Flujo completo corre sobre footage REAL del Ring Playground analizado por Bedrock (vehículo 14:05, paquete 14:07 → Rosa; 15:16 → Luis; 15:26 recogido → Ana).
- ✅ Webhooks firmados de Ring → sesión de vigilancia (en vivo con token o con footage grabado según `sub_type`).
- ⏳ Falta: escena de "paquete recogido" con footage propio (lista de tomas en docs/SHOT_LIST.md); dashboard con evidencia real + Q&A (agente trabajando).

## Fase 0 — Cimientos y spikes (cerrada)

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
| S3 Bedrock | ✅ | Nova 2 Lite + prompt v2: 54/54 en set sintético (eval/vision) y **10/10 en cuadros reales del Ring Playground** (paquete, vehículo, pájaros). ~$0.37/1k frames, p50 1.5 s. Claude bloqueado hasta enviar formulario de Anthropic. Gasto del spike: ~$2.2. |
| S4 Código de presencia | 🟡 AJUSTADO | Sintético: 100% a 30–50 cm, 0% a 1 m (QR del teléfono <2 px/módulo). Decisión: instrucción a la cuidadora "30–50 cm, 2–3 s quieta", código compacto de 25 dígitos (QR mínimo, EC M), leer cada 2–3 frames, mantener código de 6 dígitos como respaldo leído por visión. Falta validar con footage real (IR nocturno, watermark). |
| S5 Strands | ✅ | `agent.py` (Strands 1.59 + BedrockModel). Q&A familiar y resumen diario con herramientas de solo lectura; `notify` con guardrails en código. Claude Haiku 4.5 → fallback Nova Pro (Nova 2 Lite no alcanza para agente). ~$0.003/pregunta, ~2 s. `handle()` agéntico existe pero opt-in; reglas siguen por defecto. |
| S6 Notificaciones | pendiente | |

### Decisiones
- **G-S4:** el criterio "≥95% a 1 m" no se cumple → se ajusta el CÓMO (distancia 30–50 cm + código compacto + respaldo de 6 dígitos), no el alcance.
- Insulina: no hay límite de minutos sobre 8 °C (aguanta semanas a temperatura ambiente); el riesgo real es superar ~30 °C. Perfiles más estrictos (biológicos) usan `max_minutes_above_store`.
- Reconciliación determinista; el LLM solo decide acciones y redacta. El LLM nunca decide si una visita ocurrió.

### Necesito de Brandon
- ✅ AWS listo: plan Paid, presupuesto US$30/mes con alertas al correo, usuario IAM con permisos mínimos.
- Token del Playground de Ring.
