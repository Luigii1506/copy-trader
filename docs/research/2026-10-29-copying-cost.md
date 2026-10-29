# Costo de copiar y validación del Copyability Score (2026-10-29)

Datos: 26 libros activos del paper trading, hasta 478 h (20 días). Brecha = retorno del libro − retorno del trader escalado por el tope de leverage (`papertrade/tracking.py`).

## Costo de copiar

- **Mediana: −0.013 %/día (≈ −4.7 %/año)**, en línea con lo que asume el backtest (−0.018 %/día).
- **La cola es pesada:** el cuartil peor pierde ≥ 0.5 %/día frente a su objetivo.

## ¿Quién copia mal? (18 traders con brecha y fills)

| Métrica del trader | Correlación de rangos con la brecha |
|---|---|
| fills por día | **−0.66** (más actividad → peor copia) |
| duración mediana de operación | **+0.56** (más corta → peor copia) |
| share de operaciones < 15 min | −0.41 |
| **copyability_estimate (fórmula pre-declarada)** | **−0.05 (no predice)** |

Las peores brechas (−1.65 %/día y −1.30 %/día) son de traders con operaciones de **7 segundos y 12 minutos de mediana**: un sondeo de 60 s llega tarde a casi todo. Los ingredientes del Copyability Score sí predicen; **la fórmula que los combina, no**: por eso existía la regla de validarla antes de usarla.

## Consecuencias (freeze respetado)

- Nada cambia en vivo antes del veredicto.
- **Candidato v2 adicional, registrado en ADR-003 antes de usarlo:** excluir traders con duración mediana de operación < 15 min (`median_duration_h < 0.25`). Con estos datos habría excluido 7 de los 18, incluidas las 4 peores brechas.
- `copyability_estimate` se descarta como fórmula; si se usa, será con un umbral directo sobre duración/actividad.

**Muestra chica (18 traders, 9-20 días):** preliminar. Se repite al acumular más libros.
