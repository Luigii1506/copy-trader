# Cómo funciona el sistema (y qué decide)

Última actualización: 2026-10-07. Complementa [proyect.md](../../proyect.md) y [ROADMAP](../ROADMAP.md).

## El sistema no predice el mercado

No decide cuándo comprar o vender BTC. Eso lo hace el trader copiado. El sistema toma **tres decisiones**:

| Decisión | Cómo | Dónde vive |
|---|---|---|
| **¿A quién copiar?** | Rankear a todos los traders visibles por rendimiento, consistencia y riesgo; excluir vaults, cuentas chicas y HFT | `papertrade/selection.py` (hoy: 5 reglas simples; después: TraderScore) |
| **¿Cuánto a cada uno?** | Repartir el capital de la estrategia; copiar la exposición del trader en proporción a su capital; tope de leverage | `papertrade/book.py` |
| **¿Cuándo dejar de copiarlo?** | Rebalanceo periódico, caída de su capital, kill switch por drawdown; después: cambios de comportamiento | `papertrade/engine.py` |

Cuando el trader abre, cierra o cambia una posición, el libro que lo sigue la replica en proporción.

## Flujo de datos

```
Hyperliquid API ──► raw/ (JSON crudo, intocable)
                        │  collector/normalize.py
                        ▼
                    processed/ (Parquet)
                        │
          ┌─────────────┼──────────────────┐
          ▼             ▼                  ▼
  analysis/persistence  (fase 3: behavior)  papertrade/selection
  ¿hay señal?           ¿qué anticipa      ¿a quién copiar hoy?
                        una quiebra?               │
                                                   ▼
                                           papertrade/engine
                                           libros simulados, costos reales,
                                           kill switches, auditoría (SQLite)
```

## Fases

| # | Fase | Pregunta | Estado (2026-10-07) |
|---|---|---|---|
| 1 | Datos | ¿Vemos lo que hacen los traders? | Hecho. Collector, censo de ~43k curvas en curso |
| 2 | Persistencia | ¿Los buenos siguen siendo buenos? | Método listo y probado; resultado con el censo completo |
| 3 | Comportamiento | ¿Qué señales anticipan grandes pérdidas? | Siguiente |
| 4 | TraderScore | Un ranking único, backtesteado, sin look-ahead | Después de 2 y 3 |
| 5 | Paper trading | ¿Funciona en vivo con costos reales? | Corriendo desde 2026-10-06 (5 estrategias, random como control) |
| 6 | IA | Clasificar estilo de trader; explicar scores | Después de 4 |
| 7 | Capital real | — | Solo si 5 confirma a 4 durante 4-6 semanas |

**La fase 2 es la puerta.** Si no hay persistencia, se replantea todo antes de construir más.

## Dónde entra la IA (y dónde no)

El score es **determinístico y reproducible** (sección 22 del plan): mismas entradas, misma salida, backtesteable con datos de cualquier fecha. Un LLM o un modelo de juicios no puede ser la fuente de "a quién copiar" porque:

- las señales son numéricas y la estadística las procesa mejor;
- no se puede reconstruir qué habría respondido el modelo hace un año, y cambia con cada versión;
- optimizaríamos algo cuya señal base aún no está demostrada.

Usos previstos (fase 6), consistentes con la sección 21 del plan:

- **Clasificación de estilo** (scalping, swing, martingala, grid, mixto…) a partir de un resumen estructurado del comportamiento. Buen encaje para un modelo de juicios tipados como [Jev / TypeSafe](https://docs.typesafe.ai/introduction): entrada estructurada, salida con probabilidad por clase.
- **Explicabilidad** en lenguaje natural: "¿por qué 84/100 y qué alertas tiene?". Un LLM (local o API) sobre las métricas ya calculadas.
- **Features derivadas**, si acumulamos ejemplos etiquetados (traders que quebraron vs no): los juicios se vuelven columnas de un modelo clásico que sí se puede backtestear.

Opción descartada: usar un LLM para decidir entradas/salidas de operaciones. Va contra la hipótesis del proyecto (seleccionar traders, no predecir precios).
