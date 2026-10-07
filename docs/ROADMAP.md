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
| 2026-10-07 | Correr la prueba retroactiva con las 300 wallets; revisar outliers y market makers | Primera intuición (sesgada) y control de calidad de datos |
| 2026-10-07 → 09 | Leer `state/leaderboard_versions.jsonl` y ajustar el espaciado de snapshots a la cadencia real | Ahora se guarda máx. 1 cada 6 h a ciegas |
| 2026-10-08 → 10 | **Cohorte "solo curva":** ~2,000 wallets aleatorias del leaderboard (incluidas cuentas chicas y perdedoras), solo `portfolio`, sin fills | Muestra 7 veces mayor y menos sesgada para la prueba retroactiva; cuesta ~40 min de API al día |
| 2026-10-13 | **Primer resultado forward** (horizonte 1 semana) | Primera evidencia sin look-ahead |
| octubre | Verificar mercados HIP-3 (`dex`) en posiciones y fills | Podríamos no estar capturando posiciones en perpetuos de acciones |
| octubre | Dirección del builder de Invo → wallets de Invo vía `builder_fills` | Discovery de traders "copiables" |
| oct–nov | **M2 completo:** reconstruir trades y posiciones desde fills → leverage, martingala, averaging down, concentración | Las señales de comportamiento del plan (sección 18) |
| ~2026-11-05 | Primer resultado forward a 30 días | Horizonte relevante para copiar |

## Punto de decisión: ~mediados de diciembre 2026

Con ≥ 8 observaciones forward semanales y ≥ 2 mensuales:

- **Hay persistencia** (`ic_tstat ≥ 2`, `ic_positive ≥ 0.6`, mejor que `random`): construir TraderScore v1 y el simulador de paper trading (M3).
- **No hay persistencia:** documentarlo (también es un resultado) y replantear: otras señales (comportamiento, vaults), otros horizontes o abandonar la hipótesis.

Nada de dinero real antes de: backtest → out-of-sample → paper trading en vivo (sección 42 del plan).
