# Línea 2, acumulación: primer resultado (2026-10-07)

**Pregunta:** ¿un ranking de criptos (incluidas altcoins) para acumular supera a simplemente acumular BTC? ¿Funciona "comprar lo que cayó" (hipótesis del usuario) o "comprar lo fuerte" (momentum, mi apuesta previa)?

**Datos:** velas diarias de 480 monedas de Hyperliquid (todas las de cada dex, **incluidas las deslistadas**), formaciones mensuales del 2021-02 al 2026-09 (~5.6 años, incluye el bajista de 2022). Filtro de calidad: ≥180 días de historia, ≥$1M/día de volumen, no estar 95 % abajo de su máximo, seguir cotizando. Portafolio con pesos iguales, rotación mensual, 0.15 % de costo sobre lo que rota. Código: `analysis/accumulate.py`, `scripts/accumulation_study.py`.

## Resultado

| Regla | CAGR | Caída máx. | Sharpe |
|---|---|---|---|
| **Solo BTC** | **+8.9 %** | −74 % | 0.43 |
| Las 5 más caídas (comprar el dip) | −1.1 % | −86 % | 0.35 |
| Las 10 más caídas | −12.1 % | −92 % | 0.18 |
| Las 5 más fuertes (momentum) | −8.8 % | −86 % | 0.15 |
| Las 10 más fuertes | −4.8 % | −81 % | 0.18 |
| Todas las elegibles | −7.2 % | −83 % | 0.15 |
| 5 al azar (mediana de 12) | −14.5 % | — | — |

**Ninguna regla de selección de altcoins supera a BTC; todas pierden dinero en 5.6 años.** Ni momentum ni comprar lo caído. Mi predicción de que momentum ganaría a "comprar el dip" **fue incorrecta**: las diferencias entre ellas son ruido; lo robusto es que ambas pierden contra BTC. La canasta completa de altcoins elegibles cayó −7 %/año: el problema no es elegir mal, es el universo.

## Comparación pre-registrada: filtro de tendencia de 200 días

Propuesta antes de ver datos (estar invertido solo si el precio está sobre su promedio de 200 días, revisión mensual):

| | CAGR | Caída máx. | Sharpe |
|---|---|---|---|
| BTC siempre | +8.9 % | −74 % | 0.43 |
| BTC con filtro | +6.6 % | −64 % | 0.34 |
| ETH siempre | +6.9 % | −72 % | 0.45 |
| ETH con filtro | +21.5 % | −44 % | 0.60 |

**Inconcluso:** mejora mucho ETH y empeora BTC. Con 2 activos y un parámetro, no es evidencia suficiente para adoptarlo.

## Advertencias

1. Universo de Hyperliquid: muchos listados de 2023+ con sesgo a monedas de moda. Otro universo (spot top-100 histórico) podría dar distinto.
2. Precios de perps (≈ spot) sin funding; mantener longs en perps costaría además el funding.
3. El periodo arranca en febrero de 2021, cerca de un techo: el CAGR de BTC aquí (+8.9 %) es bajo frente a otros puntos de inicio.
4. Rebalanceo mensual de pesos iguales, no compras periódicas (DCA) reales.

## Decisión

- **No construir un selector de altcoins para acumular.** Los datos dicen que resta valor frente a BTC.
- La línea 2 queda como **acumulación simple de BTC (y quizá ETH) con compras periódicas**, que no necesita un sistema; si se automatiza, es un recordatorio con monto fijo, no un modelo.
- El filtro de tendencia queda anotado como hipótesis abierta, sin adoptar.
- Coincide con el resultado de la línea 1: la ventaja del proyecto está en **seleccionar traders por riesgo ajustado**, no en elegir monedas.
