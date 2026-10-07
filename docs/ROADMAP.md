# Roadmap

Visión completa en [proyect.md](../proyect.md). Alcance actual en [ADR-001](decisions/ADR-001-hyperliquid-first.md).
Regla: **primero datos → análisis → simulación → automatización → dinero.**

Última actualización: 2026-10-06.

## Hecho

- **M0 (parcial):** Hyperliquid investigado y elegido ([hyperliquid.md](platforms/hyperliquid.md)). Invo identificado como capa sobre Hyperliquid ([invo.md](platforms/invo.md)).
- **M1, data pipeline:** collector, raw → Parquet, scheduling en la Mac Studio, backup en la laptop, health check con alertas y tests.
- **M2 (inicio), método de persistencia:** [`analysis/persistence.py`](../analysis/persistence.py), validado con mundos sintéticos; notebook [01_persistence](../notebooks/01_persistence.ipynb).

## Siguiente

| Cuándo | Qué | Por qué |
|---|---|---|
| 2026-10-06 (en curso) | **Censo:** curvas de capital de ~43k traders del leaderboard, incluidos perdedores y quebrados (~22 h) | Responde la pregunta central en días, con poco sesgo de supervivencia |
| 2026-10-07 | **Primera respuesta seria de persistencia** con el censo parcial y luego completo | Decide si seguimos con TraderScore |
| 2026-10-07 → 09 | Si hay señal: TraderScore v1 + **simulador de copy trading histórico** sobre el censo (fees, slippage, sizing) | La pregunta práctica: ¿cuánto habría ganado/perdido quien copiara? |
| 2026-10-07 → 09 | Leer `state/leaderboard_versions.jsonl` y ajustar el espaciado de snapshots a la cadencia real | Ahora se guarda máx. 1 cada 6 h a ciegas |
| ~2026-10-12 | **Paper trading en vivo** con el TraderScore v1 | Es el paso que sí necesita tiempo real: validar fuera de muestra |
| 2026-10-13 | Primer resultado forward (horizonte 1 semana) | Confirmación sin look-ahead |
| octubre | Verificar mercados HIP-3 (`dex`) en posiciones y fills | Podríamos no estar capturando posiciones en perpetuos de acciones |
| octubre | Dirección del builder de Invo → wallets de Invo vía `builder_fills` | Discovery de traders "copiables" |
| oct–nov | **M2 completo:** reconstruir trades y posiciones desde fills → leverage, martingala, averaging down, concentración | Las señales de comportamiento del plan (sección 18) |
| ~2026-11-05 | Primer resultado forward a 30 días | Horizonte relevante para copiar |

## Puntos de decisión

1. **~2026-10-08, ¿hay persistencia?** Con el censo (`ic_tstat ≥ 2`, `ic_positive ≥ 0.6`, mejor que `random`).
   Si la hay, seguimos con TraderScore, simulador y paper trading. Si no, lo documentamos y replanteamos (comportamiento, vaults, otros horizontes) antes de construir más.
2. **~mediados de noviembre, ¿capital pequeño?** Solo si el paper trading en vivo (≥ 4-6 semanas) se comporta como predijo la simulación.

**Opción para acelerar todavía más:** Hyperliquid publica en S3 todos los fills de todos los usuarios (`hl-mainnet-node-data`, requester-pays). Permitiría un backtest completo a nivel de operación, pero requiere una cuenta de AWS y pagar la transferencia de datos.

Nada de dinero real antes de: backtest → out-of-sample → paper trading en vivo (sección 42 del plan).
