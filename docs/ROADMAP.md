# Roadmap

Visión completa en [proyect.md](../proyect.md). Alcance actual en [ADR-001](decisions/ADR-001-hyperliquid-first.md).
Regla: **primero datos → análisis → simulación → automatización → dinero.**

Última actualización: 2026-10-06.

## Hecho

- **M0 (parcial):** Hyperliquid investigado y elegido ([hyperliquid.md](platforms/hyperliquid.md)). Invo identificado como capa sobre Hyperliquid ([invo.md](platforms/invo.md)).
- **M1, data pipeline:** collector, raw → Parquet, scheduling en la Mac Studio, backup en la laptop, health check con alertas y tests.
- **M2 (inicio), método de persistencia:** [`analysis/persistence.py`](../analysis/persistence.py), validado con mundos sintéticos; notebook [01_persistence](../notebooks/01_persistence.ipynb). Retornos con Modified Dietz para que los depósitos no inflen resultados.
- **M2, señales de comportamiento:** [`analysis/behavior.py`](../analysis/behavior.py) reconstruye operaciones desde los fills (incl. flips y liquidaciones) y mide averaging down, martingala, leverage, concentración, sobreoperación, dependencia de un trade y cambios de estilo. Validado con secuencias sintéticas; detecta en datos reales un trader con +3,500 % de retorno, 10x de leverage mediano y 13 liquidaciones en 90 días.
- **M4 (adelantado), backtest de copy trading:** [`analysis/backtest.py`](../analysis/backtest.py): top-N por regla cada 4 semanas sin look-ahead, con costos, vs Buy & Hold BTC y vs 20 carteras aleatorias. Al correrlo con datos reales destapó tres defectos en el cálculo de retornos (ganancias spot/airdrop contadas como trading, retiros que encogían la base de capital, punto de origen sintético), ya corregidos y con tests.
  Resultado preliminar (1,265 traders, 2023-05 → 2026-09, **sesgado**: incluye las 100 wallets elegidas hoy por mayor PnL histórico): el trader promedio pierde (−3 %), random −9 % de mediana, BTC +193 %. Ninguna regla simple supera a BTC salvo "mayor PnL en USD" (+415 %), que es justo la cohorte sesgada. **No concluir nada hasta correrlo solo con el censo.**
- **M3 (adelantado), motor de paper trading:** [`papertrade/`](../papertrade), 5 estrategias en paralelo con random como control ([ADR-002](decisions/ADR-002-paper-trading.md)). Copia proporcional en todos los perp dex (incluido HIP-3), con precios de impacto, fees, funding horario, kill switches y auditoría.

## Siguiente

| Cuándo | Qué | Por qué |
|---|---|---|
| 2026-10-06 (en curso) | **Censo:** curvas de capital de ~43k traders del leaderboard, incluidos perdedores y quebrados (~30 h: comparte la cuota de API con el paper trading) | Responde la pregunta central en días, con poco sesgo de supervivencia |
| ~~2026-10-07~~ | ~~Primera respuesta de persistencia~~ **hecha: hay señal** | ver punto de decisión 1 |
| 2026-10-07 → 09 | Si hay señal: TraderScore v1 + **simulador de copy trading histórico** sobre el censo (fees, slippage, sizing) | La pregunta práctica: ¿cuánto habría ganado/perdido quien copiara? |
| 2026-10-07 → 09 | Leer `state/leaderboard_versions.jsonl` y ajustar el espaciado de snapshots a la cadencia real | Ahora se guarda máx. 1 cada 6 h a ciegas |
| 2026-10-06 17:45 PDT | **Paper trading en rodaje** (shakedown) con un pool parcial: 5 estrategias × 10 traders × $10k virtuales | Encontrar bugs en vivo antes del arranque oficial |
| ~2026-10-07 (al terminar el censo) | **Arranque oficial del paper trading:** se reinicia la base con el pool completo (universo + censo) | Que la selección inicial no dependa de un pool a medio descargar |
| cuando exista | TraderScore v1 entra como sexta estrategia | Se compara en vivo contra las demás y contra random |
| 2026-10-13 | Primer resultado forward (horizonte 1 semana) | Confirmación sin look-ahead |
| octubre | Verificar mercados HIP-3 (`dex`) en posiciones y fills | Podríamos no estar capturando posiciones en perpetuos de acciones |
| octubre | Dirección del builder de Invo → wallets de Invo vía `builder_fills` | Discovery de traders "copiables" |
| 2026-10-08 → 10 | **TraderScore v1:** combinar persistencia (rendimiento/consistencia) y comportamiento; backtest sin look-ahead sobre universo + censo; entra como sexta estrategia del paper trading | Fase 4 |
| ~2026-11-05 | Primer resultado forward a 30 días | Horizonte relevante para copiar |

## MVP (sección 36 del plan): COMPLETO 2026-10-07

| # | Punto | Dónde |
|---|---|---|
| 1-5 | Conexión, traders, estadísticas, snapshots, operaciones | collector (leaderboard horario, wallets 4×/día, censo, fills) |
| 6 | Métricas | `analysis/persistence.py`, `analysis/behavior.py` |
| 7 | TraderScore | `analysis/score.py` (walk-forward, ADR-003) |
| 8 | Mostrar ranking | dashboard, sección "Ranking TraderScore" |
| 9 | Simular copy trading | `papertrade/` (6 estrategias, risk engine, exit rules) |
| 10 | Medir resultados | dashboard (vs BTC mismo periodo y vs `random`), backtests, forward congelado |

Lo que decide "¿genera ganancias?": el forward congelado hasta el 2026-12-01 (ADR-003). Alertas a celular: pospuestas por decisión del usuario (2026-10-07) hasta validar el MVP.

## Backlog (2026-10-07)

Lo construido hasta hoy es infraestructura y medición. Lo que falta es inteligencia y control:

**Desarrollo nuevo**
1. ~~TraderScore v1~~ hecho (`analysis/score.py`, anexo en research/2026-10-07): pesos del plan validados por walk-forward (fuera de muestra: +20 % CAGR, Sharpe 2.33, DD −2 %); sexta estrategia en vivo. Falta: fills de candidatos top del censo para que las penalizaciones cubran a todos, y re-evaluar pesos con más historia.
2. ~~Backtest de copy trading~~ hecho; falta correrlo con el censo completo y por cohortes (solo censo vs universo).
3. ~~Reglas de salida por comportamiento~~ hechas (`papertrade/watch.py`, ADR-002); umbrales por calibrar con la tabla `flags`.
4. ~~Risk engine y portafolio~~ hecho (`papertrade/risk.py`, ADR-002): grupos correlacionados (21 de 33 seguidos eran uno solo), topes 30 %/trader y 50 %/grupo, pausa por pérdida diaria. Falta: allocation por score (con TraderScore).
5. ~~Realismo del simulador~~ hecho: lotes por `szDecimals`, mínimo de $10 por orden, objetivos no replicables registrados.
6. Alertas al celular (Telegram / ntfy) — espera decisión del usuario.
7. ~~Dashboard mínimo~~ hecho: `copy-trader dashboard` cada 30 min; llega a la laptop vía backup.
8. Descubrimiento vía Invo (dirección del builder → `builder_fills`).
9. Capa de IA (fase 6): clasificación de estilo y explicaciones.
10. Ejecución real (fase 7), solo tras paper trading confirmado.

**Mejoras**
- ~~Descargar fills de los traders seguidos y de los candidatos top del censo~~ hecho (cohortes `papertrade` y `candidates`: top 100 por score + top 50 por sharpe en cada corrida de wallets).
- Tracking error: ya se guarda el capital del trader junto al del libro (`book_equity`); falta el análisis.
- ~~CI en GitHub Actions~~ hecho.
- Calibrar los umbrales de las reglas de salida con los disparos registrados.

## Línea 2: acumulación inteligente — RESPONDIDA 2026-10-07

**Resultado:** con 480 monedas (deslistadas incluidas), 2021-02 → 2026-09, ninguna regla de selección de altcoins supera a acumular BTC; todas pierden dinero (momentum −8.8 %/año, comprar el dip −1.1 %/año, BTC +8.9 %/año). **Decisión: no construir un selector de altcoins; acumulación = compras periódicas de BTC (quizá ETH).** Detalle: [research/2026-10-07-accumulation.md](research/2026-10-07-accumulation.md). El texto siguiente es el plan original, conservado como registro.

### Plan original

Pedido el 2026-10-07: un ranking para **acumular** cripto (y quizá acciones), sin predecir el momento. Misma disciplina que con los traders: reglas, backtest sin look-ahead, y comparar contra acumular BTC y contra el azar.

- Score por activo: calidad (liquidez, antigüedad, no haber perdido >95 % desde máximo; en acciones, fundamentales), fuerza relativa 6-12 meses frente a su mercado, dimensionamiento por volatilidad, y compras mayores en el **núcleo** (BTC/ETH, índices) cuando está lejos de su tendencia larga. Nunca "comprar porque cayó" en altcoins.
- Salida: ranking semanal con monto sugerido por activo. Sin señales de entrada/salida.
- Experimento que lo decide: cada mes "5 más fuertes" vs "5 más caídos" vs "solo BTC" vs "5 al azar", 2020 → hoy, con costos.
- Datos: velas diarias de todas las monedas de Hyperliquid (falta capturarlas); acciones requieren fuente de precios/fundamentales y bróker en México.
- Estimación: 3-4 días. No empezar antes de la respuesta del censo y el TraderScore v1.

## Fuentes de datos adicionales (2026-10-08)

| Fuente | Qué mejoraría | Estado |
|---|---|---|
| **Vaults** (`vaultDetails`) | Copy trading nativo: depositar replica al líder exacto, sin fricción de copia; 229 vaults ≥ $10k | Recolectando a diario. **Primer estudio: sin persistencia** (universo chico y sesgado); no son mejor vehículo con la evidencia actual. [research/2026-10-08-vaults-okx.md](research/2026-10-08-vaults-okx.md) |
| **OKX Copy Trading** (API oficial pública) | Universo independiente para replicar | Recolectando a diario. **Sharpe mismo signo que en Hyperliquid, no significativo** (1 año); backtest dominado por supervivencia. Re-evaluar en 3-6 meses con las fotos diarias |
| **S3 `hl-mainnet-node-data`** (todas las operaciones históricas) | Validar históricamente las penalizaciones de comportamiento y el costo de copiar; universo sin sesgo de supervivencia | **Pendiente de decisión del usuario**: requiere cuenta AWS y pago de transferencia (requester-pays); el tamaño no se puede medir sin credenciales |
| Otros exchanges / analítica de pago | — | Descartadas: no verificables, o los mismos datos de Hyperliquid reempaquetados |

## Estado 2026-10-08

- **Evidencia:** persistencia replicada con 42k traders; Sharpe +48-54 %/año, beta 0 a BTC; TraderScore v1 falla (premia cuentas inactivas). Vaults sin señal; OKX consistente pero no significativo. Por qué solo funciona Sharpe: [research/2026-10-08-why-sharpe.md](research/2026-10-08-why-sharpe.md).
- **v2 preparada e inactiva** (`STRATEGIES_V2`): Sharpe + exclusión de inactivos, liquidados, martingala y leverage extremo. Backtest 42k: +50 %/año, DD −17 %. Se activa solo tras el veredicto del 2026-12-01.
- **Herramientas:** `copy-trader explain <trader>`, dashboard, tracking error perp vs perp.

## Congelamiento

Parámetros de decisión congelados hasta el **2026-12-01** con criterio de éxito pre-registrado: [ADR-003](decisions/ADR-003-parameter-freeze.md). Prueba de familia de señales y multiplicidad: [research/2026-10-07-signal-family.md](research/2026-10-07-signal-family.md).

## Puntos de decisión

1. ~~¿Hay persistencia?~~ **SÍ** (2026-10-07, con 20k traders del censo): las 4 señales pasan el criterio pre-registrado; top_sharpe +42 % CAGR con la mitad del drawdown de BTC; rankear por PnL (lo que hace el leaderboard) pierde dinero. Detalle y advertencias: [research/2026-10-07-persistence-census.md](research/2026-10-07-persistence-census.md). → Sigue: TraderScore v1 con walk-forward, y reinicio del paper trading con pool completo + risk engine.
2. **~mediados de noviembre, ¿capital pequeño?** Solo si el paper trading en vivo (≥ 4-6 semanas) se comporta como predijo la simulación.

**Opción para acelerar todavía más:** Hyperliquid publica en S3 todos los fills de todos los usuarios (`hl-mainnet-node-data`, requester-pays). Permitiría un backtest completo a nivel de operación, pero requiere una cuenta de AWS y pagar la transferencia de datos.

Nada de dinero real antes de: backtest → out-of-sample → paper trading en vivo (sección 42 del plan).
