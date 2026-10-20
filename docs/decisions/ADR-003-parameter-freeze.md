# ADR-003 — Congelamiento de parámetros durante el forward test

Fecha: 2026-10-07 · Estado: aceptado

## Contexto

El backtest (research/2026-10-07) es prometedor pero con señal concentrada en Sharpe y p familywise ≈ 0.07: el riesgo de overfitting no está descartado. La única prueba que lo descarta es el rendimiento **fuera de muestra con parámetros fijados de antemano**. Si ajustamos algo cada vez que el paper trading tiene una mala semana, el forward test deja de valer.

## Decisión

Quedan **congelados hasta el 2026-12-01** (≥ 8 semanas de forward) los parámetros de decisión:

| Parámetro | Valor congelado |
|---|---|
| Señales de selección en vivo | las 6 estrategias actuales, sin añadir ni quitar (salvo la Excepción 1) |
| TraderScore: pesos y penalizaciones | 25/20/20/15/10; −15/−10/−10/−5 (`analysis/score.py`) |
| Lookback / hold / N | 12 semanas / 28 días / 10 traders |
| Pool | cuenta ≥ $10k, sin vaults, sin HFT (>500 fills/día), `max_abs_ret` ≤ 1 |
| Risk engine | topes 30 %/trader, 50 %/grupo (corr ≥ 0.7), pausa diaria 5 %, halt 30 % |
| Reglas de salida | umbrales de `papertrade/config.py` y TTL 14 días |

**Sí permitido sin romper el freeze:** corregir bugs de contabilidad o datos (con test de regresión), añadir instrumentación/métricas, el embudo de fills (mejora cobertura de penalizaciones ya definidas), el dashboard, y la Línea 2 (acumulación). Cualquier excepción se registra aquí con fecha y motivo **antes** de aplicarla.

**Candidatos anotados para v2 (no aplicar antes del 2026-12-01):** N=20 (dominó en riesgo), pesos sharpe+consistency 60/40 (mejor 2ª mitad, no elegible honestamente), pausa diaria 2 % (valor del plan).

**Actualización 2026-10-08 (registrada antes de ver datos del forward):** con 41k traders el TraderScore v1 no se replicó (+5 % CAGR vs +28 % con 20k) mientras top_sharpe sí (+54 %, beta 0 a BTC). Candidato v2 principal: **selección por Sharpe, con comportamiento como filtro de exclusión** en vez de componente ponderado. Ver research/2026-10-08-census-replication.md. Nada cambia en vivo hasta el 2026-12-01.

**Actualización 2026-10-08 (b), también antes de datos del forward:** `copy-trader explain` mostró que el #1 del v1 es una cuenta inactiva (retorno 0 %, drawdown 0, 100 % pasos positivos); 3 de su top 10 lo son y el 34 % del pool es plano. Los componentes drawdown/consistencia/estabilidad premian la inactividad: es la causa mecánica de que el v1 no se replicara. v2 añade **exclusión de cuentas inactivas: volatilidad por paso < 0.2 %**. Implementado en `analysis/score.py` (`STRATEGIES_V2`, inactiva).

## Excepción 1 — 2026-10-20: `top_sharpe_pure` (aprobada por el usuario antes de aplicarla)

**Problema de diseño, no de resultados:** las reglas de salida cerraron 22 libros, casi todos por leverage p95 > 15x. `top_sharpe` quedó con 3 de 10 libros y ~70 % en efectivo hasta el rebalanceo del 2026-11-03, y todas las estrategias operan a ~0.01x. Los traders de mejor Sharpe suelen usar leverage alto, y el backtest (+48 %/año) se ganó *con* ellos (no había fills históricos para filtrar). El forward estaba probando una estrategia distinta de la validada y casi sin exposición, así que no había resultados que perseguir.

**Cambio:** se añade la estrategia `top_sharpe_pure`: la regla exacta del backtest (top 10 por Sharpe, mismo pool, mismo tope de 5x, mismos kill switches y pausa diaria) **sin reglas de salida por comportamiento**. Nada más cambia: las 6 estrategias existentes siguen igual. La diferencia `top_sharpe_pure` − `top_sharpe` mide si las reglas de salida ayudan o estorban.

**Evaluación:** `top_sharpe_pure` se evalúa el **2026-12-15** (~8 semanas desde su inicio), con el mismo criterio pre-registrado (> random y > 0 sin violar kill switches). Las demás, el 2026-12-01 como estaba.

## Criterio de éxito del forward (pre-registrado)

Al 2026-12-01, sobre las ~8 semanas: `top_score` y/o `top_sharpe` con retorno > `random` y > 0, sin violar su kill switch, y tracking error medible. Si se cumple → fase de capital pequeño (sección 42 del plan). Si no → documentar y volver a investigación sin dinero real.
