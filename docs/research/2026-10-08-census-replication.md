# Replicación con el censo completo + beta a BTC (2026-10-08)

El primer resultado (2026-10-07) usó 20k traders. El censo procesado ya tiene **41,000**: los 21k nuevos funcionan como una muestra de replicación independiente (mismo método congelado, traders que no vimos).

## 1. Persistencia: se replica

| Señal | IC (20k) | IC (41k) | t-stat (41k) |
|---|---|---|---|
| low_dd | 0.162 | 0.159 | 7.4 |
| ret | 0.121 | 0.121 | 4.7 |
| pnl_usd | 0.102 | 0.100 | 3.8 |
| sharpe | 0.089 | 0.089 | 4.2 |
| random | 0.003 | 0.000 | 0.0 |

Prácticamente idéntica: la persistencia no era un accidente de la muestra.

## 2. Backtest: **top_sharpe se sostiene; TraderScore v1 no**

| Estrategia | CAGR 20k | **CAGR 41k** | Max DD | Sharpe | 1ª mitad | 2ª mitad |
|---|---|---|---|---|---|---|
| **top_sharpe** | +42 % | **+54 %** | −17 % | 1.40 | +23 % | +40 % |
| Buy & Hold BTC | +39 % | +39 % | −50 % | 0.93 | | |
| **top_score (v1)** | +28 % | **+5 %** | −12 % | 0.46 | +10 % | +1 % |
| everyone | +5 % | +2 % | −26 % | 0.20 | | |
| top_pnl_usd | −3 % | −3 % | −74 % | 0.34 | | |
| random (mediana) | −2 % | −14 % | | | | |

**El compuesto no se replicó.** Su +28 % y su walk-forward (+20 % fuera de muestra) dependían de la muestra de 20k. El Sharpe puro sí se replicó (incluso mejoró) y es positivo en ambas mitades. Lectura honesta: la familia de señales (research/2026-10-07-signal-family) ya mostraba que solo Sharpe funcionaba sola; el compuesto mezcla Sharpe con componentes que no funcionan (consistencia, drawdown) y los diluye.

## 3. Beta a BTC: la ventaja no es BTC disfrazado

| Estrategia | Beta | Correlación | Meses BTC sube | Meses BTC baja |
|---|---|---|---|---|
| top_sharpe | **0.00** | 0.00 | +3.1 % (BTC +11.4 %) | **+4.9 %** (BTC −8.9 %) |
| top_score | 0.07 | 0.25 | +1.2 % | −0.6 % |

top_sharpe gana en meses buenos **y en meses malos** de BTC, con correlación cero: su rendimiento no viene de exposición al mercado. Es la propiedad más valiosa posible para combinar con un núcleo de BTC.

## Consecuencias (ADR-003 se respeta)

- **No se cambia nada en vivo antes del 2026-12-01.** `top_score` y `top_sharpe` siguen ambas en el paper trading: el forward decidirá con datos nuevos, que es justamente para lo que existe.
- **Candidato v2 actualizado:** el selector principal debería ser Sharpe (puro o Sharpe-dominante), con comportamiento como **filtro** (excluir) y no como componente ponderado. Se registra aquí, antes de ver los datos del forward.
- La advertencia de multiplicidad sigue en pie, pero ahora con dos piezas a favor: la replicación con 21k traders nuevos y beta cero.
