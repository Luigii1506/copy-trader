# ADR-002 — Paper trading en vivo desde ya, con varias estrategias en paralelo

Fecha: 2026-10-06 · Estado: aceptado

## Contexto

Antes de usar capital real, el plan exige paper trading en vivo (sección 42). Es el único paso que no se puede acelerar: necesita semanas de mercado real. Si esperamos al TraderScore final para empezarlo, alargamos todo el proyecto.

## Decisión

Arrancar el paper trading **ahora**, comparando en paralelo las estrategias de la sección 24 del plan. Cada día genera evidencia fuera de muestra sobre qué regla de selección funciona.

| Estrategia | Selección (pool: universo rastreado, sin vaults, cuenta ≥ $10k, sin HFT) |
|---|---|
| `leaderboard_pnl` | mayor PnL del mes según el leaderboard: lo que haría un usuario ingenuo |
| `top_return` | mayor retorno en 12 semanas (curva propia, no el ROI publicado) |
| `top_sharpe` | mayor Sharpe en 12 semanas |
| `low_drawdown` | drawdown más bajo en 12 semanas |
| `random` | al azar: **control**. Cualquier estrategia útil debe superarla |

Cada estrategia empieza con $10,000 virtuales repartidos en 10 traders y re-selecciona cada 28 días. Cuando llegue el TraderScore v1, entrará como una estrategia más.

## Cómo se copia

- **Exposición proporcional.** Si un trader tiene el 40 % de su capital total en un long de BTC, el libro que lo copia pone el 40 % de su capital en un long de BTC. El capital total del trader es el de `portfolio` (incluye cuentas unificadas y portfolio margin, que guardan el colateral en spot; usar solo la cuenta perp exageraría su leverage hasta 10 veces).
- **Leverage máximo de 5x** por libro (sección 28 del plan): si el trader usa más, escalamos todo hacia abajo.
- **Banda de rebalanceo:** solo se opera si el cambio supera el 10 % de la posición o $10, para no simular comisiones por ruido.
- **Todos los perp dex**, incluidos HIP-3 (acciones e índices).

## Costos simulados

- **Ejecución:** precios de impacto de Hyperliquid (`impactPxs`, el costo real de cruzar el libro con un tamaño de referencia), con un mínimo de 2 bps sobre el mid.
- **Fee taker:** 0.045 % (nivel base; los mercados HIP-3 pueden variar).
- **Funding cada hora:** `tamaño × precio oráculo × tasa` (fórmula oficial).
- **Latencia:** sondeo cada 60 s. Los traders de alta frecuencia no se pueden copiar así y se excluyen del pool (más de 500 fills por día).

## Cuándo dejar de copiar (reglas de salida)

Cada 6 h el motor evalúa a los traders seguidos con las señales de comportamiento (`analysis/behavior.py`) sobre sus últimos 60 días. Un trader marcado se cierra y no se vuelve a elegir durante 14 días. Reglas iniciales (`papertrade/config.py`), **sin calibrar todavía**; cada disparo queda en la tabla `flags` para calibrarlas después:

| Regla | Condición |
|---|---|
| `liquidated` | alguna liquidación forzada en la ventana |
| `martingale` | agranda el tamaño tras perder en > 60 % de los casos |
| `leverage` | p95 del leverage > 15x |
| `leverage_escalation` | leverage reciente > 2× el anterior |
| `size_escalation` | tamaño reciente > 3× el anterior |

Requiere ≥ 5 operaciones cerradas en la ventana. Para que haya fills de los traders seguidos, el collector los agrega al universo (cohorte `papertrade`).

## Riesgo y control

- **Kill switch por estrategia:** si cae 30 % desde su máximo, cierra todo y se detiene. Es más laxo que el 10 % del plan, a propósito: aquí queremos medir cada regla de selección, no detenerla en la primera racha. El risk engine de producción usará los límites del plan.
- **Kill switch global:** `copy-trader papertrade-halt` cierra todo.
- **Observabilidad:** cada operación queda registrada con su motivo (exposición del trader, objetivo, precio y costos) en SQLite (sección 30 del plan).

## Consecuencias

- Los resultados de las primeras semanas serán ruido. Se evalúan junto con la prueba de persistencia.
- El sondeo de 60 s subestima lo que costaría copiar a traders muy activos. Medir el **tracking error** (nuestro retorno vs el del trader) es parte del análisis.
