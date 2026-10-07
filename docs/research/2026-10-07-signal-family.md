# Prueba de familia de señales y robustez de parámetros (2026-10-07)

Respuesta a la crítica externa: "si solo Sharpe-con-parámetros-exactos funciona y sus primos caen, sospecha overfitting". Censo (~20k traders), N=10, lookback 12 sem, hold 4 sem, con costos, salvo donde se indica.

## 1. Robustez de parámetros del Sharpe: PASA

| Variación | CAGR | Max DD | Sharpe |
|---|---|---|---|
| lookback 8 / **12** / 16 / 26 sem | +61 / **+42** / +25 / +14 % | −31/−22/−23/−17 % | 0.82 / 1.41 / 0.96 / 0.85 |
| N = 5 / **10** / 20 | +48 / **+42** / +51 % | −22/−22/**−12 %** | 1.34 / 1.41 / **1.56** |
| hold = 2 / **4** / 8 sem | +29 / **+42** / +54 % | −24/−22/−41 % | 1.15 / 1.41 / 1.10 |

Ningún pico aislado: todo el grid gana a random (+4.6 %) con Sharpe ≥ 0.82. El decaimiento suave con lookback más largo (señal más fresca = más fuerte) es un patrón, no un accidente. Nota: N=20 domina a N=10 en riesgo; candidato para v2, **no** se cambia ahora (ver ADR-003).

## 2. Familia de señales: NO acompaña — el hallazgo honesto

| Selector (12 sem) | CAGR | Sharpe |
|---|---|---|
| **sharpe** | **+42 %** | **1.41** |
| composite_score (pesos del plan) | +28 % | 0.99 (Calmar 1.96) |
| consistency | +8.8 % | 0.42 |
| sortino | +7.7 % | 0.37 |
| calmar | +7.2 % | 0.45 |
| profit_factor | +6.4 % | 0.33 |
| low_dd | **−6.6 %** | −0.09 |
| random | +4.6 % | 0.31 |

Hipótesis mecánica probada y **rechazada**: no es degeneración por muestra corta (con lookback 26 sem, sortino/calmar empeoran a −2 %).

Explicación restante (económica, por verificar): sortino/calmar/low_dd premian "aún no ha perdido", que en perps selecciona perfiles de cola oculta (martingala/grid: muchas ganancias pequeñas hasta el estallido). `low_dd` perdiendo dinero activamente apoya esta lectura. El Sharpe castiga la irregularidad también al alza y evita esa trampa. **Pregunta verificable pendiente:** ¿los top-sortino muestran más `martingale_share`/liquidaciones posteriores? (necesita el embudo de fills).

## 3. Multiplicidad, en números

Sharpe 1.41 en 3.3 años → t ≈ 2.6 (p ≈ 0.01). Probamos 8 selectores → p familywise ≈ 0.07. **Por sí solo, marginal.** Lo que lo sube de "marginal" a "prometedor": la regla estaba pre-especificada en el plan (sección 24) antes de ver datos, el grid de parámetros es robusto, funciona en ambas mitades (+19 % / +96 %), y el compuesto pre-registrado también funciona. Lo que lo decide de verdad: los dos forward tests ya corriendo (paper trading y leaderboard semanal).

## Valoración actualizada (formato de la crítica)

🟢 Hipótesis e historia económica coherentes · 🟢 Robustez de parámetros y mitades · 🟡 **Señal concentrada en Sharpe + compuesto; familywise p ≈ 0.07: el overfitting no está descartado** · 🔴 Rentabilidad futura garantizada: ninguna. El juez es el forward test con parámetros congelados (ADR-003).
