# CHECKPOINT — pausa 11-oct-2026, 3:30 pm (Tampico)

> Leer esto + `STATUS.md` al retomar. Todo está commiteado en `main`.

## 1. Qué está construido y funcionando
| Pieza | Estado | Dónde |
|---|---|---|
| SDK open source `ringpartner` (REST sync/async, WHEP, webhooks HMAC, simulador firmado, record/replay, CLI) | ✅ 55 tests | `packages/ringpartner/` |
| Presence codes (QR firmado rotativo + compacto + 6 dígitos) y lector OpenCV | ✅ 26 tests, eval sintético | `core/.../presence*.py`, `eval/presence/` |
| Caregiver Pass (web móvil, paridad JS↔Python probada) | ✅ | `web/caregiver-pass/index.html`, servido en `/pass` |
| Visión Bedrock (Nova 2 Lite + prompt v2) | ✅ 54/54 sintético, 10/10 Ring real | `core/.../vision.py`, `eval/vision/` |
| Watcher: frames Ring → visión + códigos → PorchTracker k-de-n → Engine | ✅ | `core/.../watcher.py` |
| Engine + reconciliación determinista + modelo térmico (calor **y congelación**) | ✅ | `engine.py`, `reconcile.py`, `exposure.py` |
| Responder con guardrails + Writer Bedrock (Claude → Nova → plantillas) | ✅ | `responder.py` |
| CareAgent Strands (Q&A familiar + resumen diario, Claude → Nova Pro) | ✅ 12 tests | `agent.py`, `docs/agent_spike.md` |
| Live controller: webhooks firmados de Ring → sesión de vigilancia; vigilancia por ventanas de cuidado | ✅ | `live.py`, `POST /webhooks/ring` |
| API FastAPI + SSE + EVV CSV + demo runner | ✅ | `api.py` |
| Dashboard Next.js (Today / Agency / Ledger, Ask, resumen, evidencia real) | ✅ build OK | `web/dashboard/` |
| Footage real del Ring Playground (paquete, vehículo, movimiento) | ✅ | `fixtures/ring_playground/` (CC BY 4.0 del clip de paquete → atribuir) |
| Friction log | ✅ 8 entradas | `FRICTION_LOG.md` |

**Tests:** 93 passed, 1 skipped (`uv run pytest -q`).
**Gasto AWS aprox.:** ~US$2.5 (casi todo el spike de visión). Presupuesto US$30/mes con alertas.

**Correr el demo:** preview servers `doorledger-api` (8787) y `doorledger-dashboard` (3000) en `~/.claude/launch.json` → dashboard → tecla **D** → escenario.

## 2. Historia del demo (decisión 11-oct)
Invierno en Chicago: la insulina se deja en un porche a −9 °C (el clip de paquete del Ring Playground es un escalón nevado). 14:07 Ring ve el paquete → aviso a Rosa; 14:27 en riesgo de congelarse → vecino Luis; 14:37 → Ana (hija); 14:40 recogido → aviso a Ana. Mañana: Maria (cuidadora) llega 22 min tarde y se queda 43/120 min → agencia y familia.

## 3. Qué falta (por prioridad)
1. 👤 **Footage propio** (docs/SHOT_LIST.md): cuidadora con QR (check-in/out) + paquete recogido → reemplaza los pasos `SIMULATED`. Al grabar: fijar el secreto de la visita en `fixtures/own_footage/visit.json` y `recorded_start` para verificar códigos al reproducir.
2. 👤 **Claude en Bedrock:** formulario de Anthropic enviado 11-oct 3:27 pm; Haiku 4.5 aún daba "use case not submitted" a las 3:30 (tarda ~15 min). Haiku 5.5 dice "not available for this account" → reintentar; si sigue, usar Haiku 4.5. Ojo: modelos 5.5 rechazan `temperature: 0` (vision.py la manda).
3. 👤 **Telegram (S6):** bot de @BotFather → `TELEGRAM_BOT_TOKEN` + chat id en `.env`.
4. **Dashboard:** el modo mock aún dice Tampa/calor → pasar a Chicago/invierno; nombre de escenario `porch_cold` (alias `porch_heat` existe); mostrar "límite: congelación 32 °F" cuando `estimate.direction == "cold"` (campos nuevos `direction`, `unsafe_c`).
5. **README principal** + diagrama de arquitectura + atribución CC BY + guía de ejecución.
6. **AWS Builder (multi-servicio):** desplegar el agente en Bedrock AgentCore Runtime (plan en `docs/aws_architecture.md`), espejo del ledger en DynamoDB, receptor de webhooks en Lambda/API Gateway.
7. **Open Source:** repo público en GitHub (HaDeZIB/doorledger), publicar `ringpartner` en PyPI, CI con GitHub Actions.
8. **Video (<3 min, inglés)** + texto de Devpost + feedback por herramienta.

## 4. Ideas de mejora detectadas en la revisión (para la siguiente carga)
- **Mensajes bilingües:** Rosa recibe en español, Ana en inglés (familia hispana; muestra comprensión del usuario final). Campo `language` por persona → el Writer escribe en ese idioma.
- **Privacidad por diseño:** difuminar caras en los cuadros de evidencia guardados (solo se conserva lo necesario para probar el evento). Muy valorado por un jurado de Ring.
- **Paquete de evidencia para la farmacia:** PDF con línea de tiempo, temperatura estimada y cuadros del Ring → reclamo de reposición en un clic.
- **Costo de visión:** clasificar solo cuando hay movimiento (diferencia entre cuadros) y bajar a 1 cuadro cada 3 s cuando el porche está estable; prefiltro barato con Nova Lite.
- **Multi-cámara** (criterio creativo de Ring): segunda cámara (cochera) para "vehículo llegó" + puerta para "paquete" — el Playground solo tiene 1 dispositivo, pero el SDK ya soporta `component_id`.
- **Threshold (v2):** "tiempo para abrir la puerta" / velocidad al caminar como indicador de fragilidad.
- **Rate limit** de códigos de presencia por timbre (riesgo anotado en eval/presence).
- **Reporte semanal** para la agencia: % visitas verificadas, minutos entregados vs. facturados.
