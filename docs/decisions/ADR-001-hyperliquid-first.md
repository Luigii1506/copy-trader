# ADR-001 — Hyperliquid primero, alcance reducido a investigación

Fecha: 2026-10-06 · Estado: aceptado

## Contexto

El plan original ([proyect.md](../../proyect.md)) describe un sistema completo de copy trading. Antes de construirlo tenemos que responder una pregunta que puede invalidarlo todo: **¿el rendimiento/riesgo pasado de un trader predice su rendimiento futuro?**

Además, el historial por trader en las plataformas suele ser limitado. Los datos que no capturemos hoy no los podremos recuperar después.

## Decisión

1. **Nuevo objetivo inicial:** construir un dataset histórico de traders de Hyperliquid y medir si existe persistencia de rendimiento.
2. **Hyperliquid primero.** Sus datos son on-chain y públicos: fills, posiciones y curva de capital de cualquier wallet, sin depender de un ROI publicado.
3. **Invo como posible capa de discovery** (está construida sobre Hyperliquid), no como infraestructura.
4. **El collector empieza ya,** antes de que el resto del sistema exista.
5. **Stack de investigación:** Python + JSON crudo (gzip) → Parquet + DuckDB + Polars + Jupyter. PostgreSQL, FastAPI, Next.js, Redis, alertas, Docker, IA y ejecución real se posponen hasta que los datos muestren señal.
6. **A vs B** (copy nativo vs replicar señales) queda abierto. B es preferible conceptualmente por el control sobre sizing, riesgo y salida.

## Diseño del collector

- **Leaderboard completo diario** (~47k wallets). Es la base del análisis de persistencia sobre todo el universo, incluidas las wallets que pierden o desaparecen.
- **Universo rastreado append-only:** top 100 PnL histórico, top 100 ROI 30d (cuenta ≥ $10k) y **100 aleatorias como grupo de control** (con semilla registrada). Nunca se elimina una wallet.
- **Por wallet:** `clearinghouseState`, `portfolio` y fills incrementales.
- Todo se guarda crudo, con un envelope (`platform`, `dataset`, `fetched_at`, `request`, `payload`).

## Primer experimento

Persistencia: rankear las wallets en t0 por ROI, Sharpe, bajo drawdown y TraderScore, y medir su posición en t+30/60/90 días contra un **grupo aleatorio**. Antes de confiar en cualquier ranking:
- exigir un mínimo de operaciones;
- ajustar por pruebas múltiples (Deflated Sharpe Ratio).

Un resultado negativo también es válido y nos ahorra construir el sistema completo.

## Consecuencias

- Dependemos de un endpoint no documentado (leaderboard). Mitigación: guardamos el crudo y las wallets descubiertas siguen siendo consultables por la API oficial.
- El collector debe correr de forma continua. En una laptop habrá huecos cuando esté apagada; a mediano plazo conviene un VPS.
