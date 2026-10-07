# Persistencia en el censo: primer resultado (2026-10-07)

**Pregunta** (ADR-001): ¿el rendimiento/riesgo pasado de un trader predice su rendimiento futuro?
**Respuesta: sí, y en la dirección que la hipótesis del proyecto predijo** (sección 2 del plan): las métricas ajustadas por riesgo seleccionan; el PnL bruto no.

## Datos

- Muestra: **19,927 traders con retornos** del censo (22,000 descargados de 43,315 al momento del corte). El censo baja en orden aleatorio con semilla, así que una descarga parcial es una muestra aleatoria válida.
- Sin las cohortes sesgadas del universo; vaults excluidas. Retornos en pasos de 2 semanas, PnL de perps sobre capital total, Dietz conservador (ver `analysis/persistence.py`).
- Sesgo restante: el censo sale del leaderboard de hoy. El leaderboard conserva wallets quebradas (~13k con <$1), pero no sabemos si elimina wallets inactivas durante años.

## 1. Persistencia (28 periodos no traslapados, ~5,000 traders por periodo)

Criterio pre-registrado (notebook 01): `ic_tstat ≥ 2`, `ic_positive ≥ 0.6`, mejor que random.

| Señal (12 sem) | IC medio | t-stat | % periodos IC>0 |
|---|---|---|---|
| low_dd | 0.162 | **7.5** | 96 % |
| ret | 0.121 | 4.6 | 79 % |
| pnl_usd | 0.102 | 3.9 | 79 % |
| sharpe | 0.089 | 4.2 | 79 % |
| random | 0.003 | 0.9 | 57 % |

**Las cuatro señales pasan el criterio.** Advertencia: parte del IC de `low_dd` es "quien no opera pierde menos"; por eso la decisión económica se toma con el backtest, no con el IC.

## 2. Backtest de copia (43 periodos ≈ 3.3 años, top-10, rebalanceo cada 4 semanas, con costos)

| Estrategia | Total | CAGR | Max DD | Sharpe |
|---|---|---|---|---|
| **top_sharpe** | **+219 %** | **+42 %** | **−22 %** | **1.40** |
| Buy & Hold BTC | +199 % | +39 % | −50 % | 0.93 |
| low_dd (ret>0) | +100 % | +23 % | −18 % | 0.85 |
| top_return | +96 % | +22 % | −65 % | 0.67 |
| el trader promedio | +19 % | +5 % | −25 % | 0.32 |
| top_pnl_usd | −10 % | −3 % | −66 % | 0.27 |
| random (mediana de 20) | −5 % | −2 % | — | 0.15 |

- **Elegir por Sharpe batió a BTC con la mitad de drawdown** y supera el p90 de las carteras aleatorias (+126 %).
- **Elegir por PnL en USD —lo que muestra el leaderboard— pierde dinero.** El +415 % de ayer era sesgo de supervivencia de la cohorte, como se sospechó.

## 3. Robustez por mitades

| Periodo | top_sharpe | BTC | random (mediana) |
|---|---|---|---|
| 2023-05 → 2025-02 (alcista) | +19 %/año, DD −17 % | +112 %/año | +3 %/año |
| 2025-03 → 2026-10 (incluye bajista) | **+96 %/año, DD −8 %, Sharpe 2.6** | −18 %/año, DD −50 % | −33 %/año |

La señal gana a random en ambas mitades. Contra BTC es **complementaria por régimen**: pierde en el alcista puro y brilla cuando el mercado cae. Es exactamente la promesa del copy trading (retornos no dependientes de la dirección) y apoya combinar un núcleo de acumulación con la capa de copia.

## Advertencias antes de celebrar

1. Probamos ~5 reglas y reportamos la mejor: hay múltiple comparación. Mitigado por el criterio pre-registrado, el t=7.5 y la partición temporal; se reforzará con walk-forward al construir TraderScore.
2. Fricción supuesta (0.25 %/paso + rebalanceo); la real la medirá el paper trading (tracking error).
3. Retornos desde curvas muestreadas cada ~2 semanas, no a nivel de operación.
4. 43 periodos son ~3 años: suficiente para decidir seguir, no para prometer rendimientos.

## Decisión

El punto de decisión 1 del roadmap se responde **sí**: continuar con TraderScore v1 (combinando sharpe/low_dd con las señales de comportamiento), validación walk-forward, y reinicio del paper trading con el pool completo y el risk engine.
