# AI Copy Trading Intelligence

## 1. Objetivo del proyecto

Construir un sistema automatizado de **inteligencia, selección y copy trading de traders de criptomonedas**.

El sistema no intentará predecir directamente si Bitcoin, Ethereum u otro activo va a subir o bajar.

La hipótesis principal es:

> Es posible obtener mejores resultados seleccionando sistemáticamente traders con buen rendimiento ajustado por riesgo, consistencia y comportamiento estable, en lugar de copiar indiscriminadamente a los traders con mayor ROI.

El proyecto tendrá inicialmente tres objetivos:

1. Recopilar datos de plataformas de copy trading.
2. Analizar y rankear traders mediante métricas propias.
3. Simular copy trading mediante paper trading.

Solo después de demostrar resultados consistentes se evaluará utilizar capital real.

---

# 2. Hipótesis

## Hipótesis principal

Los traders con el mayor ROI no necesariamente son los mejores traders para copiar.

Un trader puede tener:

- ROI extremadamente alto
- drawdown extremadamente alto
- leverage excesivo
- martingale
- concentración excesiva
- pocas operaciones
- resultados dependientes de una sola operación

Por lo tanto necesitamos un sistema que evalúe:

```text
Performance
+
Risk
+
Consistency
+
Longevity
+
Behavior
+
Strategy Stability
```

y produzca un `TraderScore`.

---

# 3. Plataformas iniciales

Las primeras plataformas a investigar serán:

1. Invo
2. Hyperliquid
3. Bybit
4. Bitget
5. OKX
6. Binance
7. BingX

No debemos asumir que todas serán utilizadas finalmente.

La primera fase debe determinar cuáles ofrecen:

- API pública
- API privada
- datos históricos
- datos de traders
- posiciones
- operaciones
- estadísticas
- ejecución
- copy trading
- webhooks
- WebSocket
- límites de API
- disponibilidad desde México

---

# 4. Principio fundamental

## No depender de la métrica proporcionada por la plataforma

Si una plataforma dice:

```text
Trader A
ROI: +180%
```

no debemos convertir automáticamente eso en:

```text
Score = 180
```

Debemos descargar los datos disponibles y construir nuestras propias métricas.

Ejemplo:

```text
Raw Data
    ↓
Normalization
    ↓
Feature Engineering
    ↓
Risk Metrics
    ↓
Behavior Analysis
    ↓
TraderScore
```

---

# 5. Arquitectura inicial

```text
                 ┌─────────────────────┐
                 │   Exchange APIs      │
                 │ Invo / Hyperliquid   │
                 │ Bybit / Bitget       │
                 │ OKX / Binance        │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │   Data Collectors   │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │    Raw Storage      │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Normalization Layer │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Feature Engineering │
                 └──────────┬──────────┘
                            │
                 ┌──────────┴──────────┐
                 ▼                     ▼
        ┌─────────────────┐   ┌─────────────────┐
        │  Risk Engine    │   │ Behavior Engine │
        └────────┬────────┘   └────────┬────────┘
                 │                     │
                 └──────────┬──────────┘
                            ▼
                 ┌─────────────────────┐
                 │    TraderScore      │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Portfolio Selector  │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │   Paper Trading     │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Performance Analysis│
                 └─────────────────────┘
```

---

# 6. Arquitectura por fases

No construir todo al mismo tiempo.

## Fase 0 — Research

Objetivo:

Determinar qué plataforma utilizar.

Entregables:

```text
docs/platforms/invo.md
docs/platforms/hyperliquid.md
docs/platforms/bybit.md
docs/platforms/bitget.md
docs/platforms/okx.md
docs/platforms/binance.md
docs/platforms/bingx.md
```

Cada documento debe responder:

- ¿Tiene API?
- ¿Qué endpoints existen?
- ¿Qué datos de traders ofrece?
- ¿Existe histórico?
- ¿Hay WebSocket?
- ¿Existe copy trading?
- ¿Puede ejecutar órdenes?
- ¿Puede consultar posiciones?
- ¿Rate limits?
- ¿Autenticación?
- ¿Restricciones geográficas?
- ¿Comisiones?
- ¿Términos de uso?
- ¿Es posible automatizarlo?
- ¿Existe SDK?
- ¿Existe documentación oficial?

---

# 7. Fase 1 — Data Collector

Crear un sistema que pueda descargar datos de traders.

Ejemplo conceptual:

```python
Trader(
    platform="bybit",
    trader_id="abc123",
    name="Trader",
    roi=0.32,
    pnl=4210,
    max_drawdown=0.08,
    win_rate=0.61,
)
```

Pero el modelo real debe conservar los datos originales.

Nunca almacenar únicamente las métricas calculadas.

---

# 8. Raw Data

Guardar primero los datos originales.

Ejemplo:

```text
data/
    raw/
        bybit/
        bitget/
        okx/
        hyperliquid/
```

Ejemplo:

```json
{
  "platform": "example",
  "trader_id": "12345",
  "timestamp": "2026-10-06T12:00:00Z",
  "payload": {}
}
```

Esto permite recalcular métricas posteriormente.

---

# 9. Base de datos

Inicialmente:

**PostgreSQL**

Tablas principales:

```text
platforms
traders
trader_snapshots
trader_metrics
positions
trades
portfolio_snapshots
scores
strategies
paper_orders
paper_positions
paper_portfolio_snapshots
```

---

# 10. Trader

Modelo conceptual:

```text
Trader

id
platform
external_id
name
first_seen_at
last_seen_at
status
```

Nunca asumir que el nombre es un identificador único.

La identidad debe ser:

```text
platform + external_id
```

---

# 11. Trader snapshots

Guardar snapshots periódicos.

Ejemplo:

```text
trader_id
timestamp

roi
pnl
aum
followers
win_rate
profit_share
drawdown
trades_count
```

Esto permitirá construir series temporales.

---

# 12. Trades

Registrar cada operación cuando sea posible.

Campos:

```text
id
trader_id
platform
external_trade_id

symbol
side

entry_price
exit_price

quantity
notional

leverage

opened_at
closed_at

realized_pnl
fees
funding

raw_data
```

---

# 13. Positions

Las posiciones abiertas son importantes para detectar comportamiento.

Registrar:

```text
symbol
side
size
entry_price
mark_price
leverage
unrealized_pnl
liquidation_price
opened_at
```

---

# 14. Data Collection

Debe existir un scheduler.

Ejemplo:

```text
Every 1 minute
    ↓
Active positions

Every 5 minutes
    ↓
Trader statistics

Every 1 hour
    ↓
Trader discovery

Every 24 hours
    ↓
Historical aggregation
```

La frecuencia real dependerá de los límites de cada plataforma.

---

# 15. Normalización

Cada plataforma utiliza nombres y estructuras diferentes.

Crear un modelo común:

```text
PlatformTrader
PlatformTrade
PlatformPosition
PlatformPerformance
```

Cada adapter convierte:

```text
Bybit response
      ↓
BybitAdapter
      ↓
NormalizedTrader
```

Lo mismo:

```text
BitgetAdapter
OKXAdapter
HyperliquidAdapter
```

Esto evita contaminar el core del sistema con lógica específica de cada plataforma.

---

# 16. Interface de plataforma

Definir una interfaz similar a:

```python
class TradingPlatform(Protocol):

    def get_traders(...):
        ...

    def get_trader_stats(...):
        ...

    def get_trader_trades(...):
        ...

    def get_trader_positions(...):
        ...

    def get_market_data(...):
        ...

    def get_account_balance(...):
        ...

    def place_order(...):
        ...

    def cancel_order(...):
        ...
```

La ejecución de órdenes debe permanecer separada del análisis.

---

# 17. Feature Engineering

A partir de los datos construiremos características.

## Performance

```text
ROI
PnL
CAGR
Daily return
Weekly return
Monthly return
```

## Risk

```text
Maximum Drawdown
Average Drawdown
Volatility
Downside Volatility
Value at Risk
Expected Shortfall
```

## Risk-adjusted performance

```text
Sharpe Ratio
Sortino Ratio
Calmar Ratio
```

## Consistency

```text
% profitable days
% profitable weeks
% profitable months

consecutive profitable periods

return variance
```

---

# 18. Behavioral Features

Esta será una parte importante del proyecto.

Detectar:

### Martingale

```text
Loss
 ↓
Increase position
 ↓
Loss
 ↓
Increase position
 ↓
Loss
 ↓
Increase position
```

### Averaging down

```text
Price ↓
Position ↑
Price ↓
Position ↑
```

### Leverage escalation

```text
2x
3x
5x
10x
20x
```

### Revenge trading

Después de una pérdida:

```text
loss
 ↓
large position
 ↓
large leverage
```

### Concentration

Ejemplo:

```text
BTC      70%
ETH      20%
Others   10%
```

### Overtrading

```text
100+ trades/day
```

### Strategy change

Detectar cambios abruptos en:

- leverage
- symbols
- trade duration
- position size
- win rate
- frequency

---

# 19. TraderScore

Primera versión experimental:

```text
TraderScore =
    25% Risk-adjusted Return
    20% Drawdown
    20% Consistency
    15% Longevity
    10% Strategy Stability
    10% Behavioral Risk
```

IMPORTANTE:

Estos pesos son únicamente un punto de partida.

No asumir que son óptimos.

Debemos probarlos mediante backtesting.

---

# 20. Penalizaciones

Ejemplo conceptual:

```text
Base Score = 87

Martingale          -20
High leverage       -10
High concentration   -5
Strategy instability -10

Final Score = 42
```

Nunca permitir que un ROI extremadamente alto compense completamente un riesgo extremo.

---

# 21. AI Layer

La IA NO debe decidir directamente:

```text
BUY BTC
SELL BTC
```

Inicialmente utilizarla para:

### Clasificación

```text
Trader type:

trend following
mean reversion
scalping
swing
high frequency
martingale
grid
mixed
unknown
```

### Explicabilidad

Generar:

```text
¿Por qué este trader obtuvo 84/100?
```

Ejemplo:

```text
Strong consistency
Low drawdown
Moderate leverage
18 months history

Warnings:
Increasing position size
High BTC concentration
```

---

# 22. No utilizar LLM como fuente principal del score

El score debe ser principalmente matemático/determinístico.

```text
Raw data
 ↓
Metrics
 ↓
Score
```

La IA puede complementar:

```text
Metrics
 +
Behavior
 +
Historical patterns
 ↓
AI interpretation
```

Esto hace el sistema más reproducible.

---

# 23. Paper Trading

Antes de dinero real crear un simulador.

Ejemplo:

```text
Capital:
$1,000 USD

Trader allocation:

Trader A   30%
Trader B   25%
Trader C   20%
Trader D   15%
Cash       10%
```

Cuando un trader abre una posición:

```text
Real trader
     ↓
Signal
     ↓
Paper execution
```

No ejecutar dinero real.

---

# 24. Estrategias a comparar

Crear diferentes estrategias.

### Strategy A — ROI

Copiar los traders con mayor ROI.

### Strategy B — Sharpe

Seleccionar mayor Sharpe.

### Strategy C — Drawdown

Priorizar bajo drawdown.

### Strategy D — TraderScore

Usar nuestro modelo.

### Strategy E — Risk-adjusted

TraderScore + portfolio diversification.

### Strategy F — Dynamic

Modificar allocation según:

- performance
- drawdown
- volatility
- correlation
- behavior

---

# 25. Backtesting

El backtest debe evitar look-ahead bias.

No podemos seleccionar traders utilizando información que todavía no existía en el momento simulado.

Incorrecto:

```text
Usar resultados de 2026
para decidir qué trader copiar
en enero de 2025
```

Correcto:

```text
Información disponible hasta enero
        ↓
Decisión
        ↓
Simulación febrero
```

---

# 26. Walk-forward testing

Utilizar:

```text
Train / calibration
        ↓
Validation
        ↓
Out-of-sample
```

Ejemplo:

```text
2024 ────────> desarrollar modelo
2025 ────────> validar
2026 ────────> out-of-sample
```

La fecha real dependerá de la disponibilidad de datos.

---

# 27. Portfolio Management

No queremos necesariamente copiar 1 trader.

Podemos construir un portfolio.

Ejemplo:

```text
Trader A   30%
Trader B   25%
Trader C   20%
Trader D   15%
Cash       10%
```

Pero debemos considerar correlación.

Si:

```text
Trader A
Trader B
Trader C
```

todos básicamente hacen BTC long con leverage alto, no estamos realmente diversificando.

---

# 28. Risk Engine

Debe poder imponer límites independientes del trader.

Ejemplo:

```text
MAX_PORTFOLIO_DRAWDOWN = 10%

MAX_TRADER_ALLOCATION = 30%

MAX_POSITION_SIZE = 5%

MAX_LEVERAGE = 5x

MAX_DAILY_LOSS = 2%

MAX_CORRELATED_EXPOSURE = 50%
```

Si se viola un límite:

```text
STOP COPYING
```

---

# 29. Kill Switch

Debe existir un mecanismo para detener todo.

Ejemplo:

```text
Emergency Stop
```

Debe poder:

```text
cancel pending orders
stop new positions
close positions
disable copy engine
```

La implementación exacta dependerá de la plataforma.

---

# 30. Observabilidad

Necesitamos saber exactamente qué está haciendo el sistema.

Registrar:

```text
decision
reason
timestamp
trader
score
allocation
signal
execution
result
```

Ejemplo:

```text
2026-10-06

Trader A
Score: 86
Allocation: 20%

Reason:
High consistency
Low drawdown
Moderate leverage
No behavioral warnings
```

---

# 31. Dashboard

Primera versión:

```text
Dashboard

Portfolio
─────────────
Capital
PnL
ROI
Drawdown
Sharpe

Traders
─────────────
Trader
Score
ROI
Drawdown
Risk
Status

Positions
─────────────
Symbol
Side
Size
PnL

Alerts
─────────────
Risk warning
Trader removed
Drawdown exceeded
API error
```

---

# 32. Alertas

Inicialmente:

- Telegram
- Discord
- Email

Alertas:

```text
Trader dropped below score threshold

Portfolio drawdown exceeded

Trader changed strategy

High leverage detected

API disconnected

Order execution failed
```

---

# 33. Seguridad

Nunca guardar API keys en código.

Usar:

```text
.env
Secrets Manager
encrypted credentials
```

Nunca utilizar API keys con permisos de retiro.

Idealmente:

```text
Trading: YES
Withdrawal: NO
```

---

# 34. Arquitectura tecnológica inicial

## Backend

Python.

Motivo:

- data engineering
- APIs
- pandas/polars
- ML
- backtesting
- async
- trading libraries

## Database

PostgreSQL.

## Cache

Redis opcional.

## Queue

Inicialmente puede evitarse.

Después:

```text
Redis / RabbitMQ / Kafka
```

si realmente hace falta.

## Frontend

Next.js + React.

## API

FastAPI.

## Scheduler

Inicialmente:

```text
APScheduler
```

o cron.

Posteriormente:

```text
Temporal
Celery
Dagster
```

si aumenta la complejidad.

---

# 35. Repository

Propuesta:

```text
copy-trading-intelligence/
│
├── apps/
│   ├── api/
│   ├── web/
│   └── worker/
│
├── packages/
│   ├── domain/
│   ├── platforms/
│   ├── analytics/
│   ├── risk/
│   ├── scoring/
│   ├── backtesting/
│   └── execution/
│
├── data/
│   ├── raw/
│   └── processed/
│
├── tests/
│
├── docs/
│   ├── platforms/
│   ├── architecture/
│   ├── research/
│   └── decisions/
│
├── scripts/
│
├── migrations/
│
├── .env.example
├── docker-compose.yml
├── README.md
└── pyproject.toml
```

---

# 36. MVP

NO construir todo inicialmente.

El MVP debe hacer solamente:

```text
1. Conectarse a una plataforma

2. Obtener traders

3. Obtener estadísticas

4. Guardar snapshots

5. Obtener operaciones cuando sea posible

6. Calcular métricas

7. Crear TraderScore

8. Mostrar ranking

9. Simular copy trading

10. Medir resultados
```

No necesitamos todavía:

- app móvil
- usuarios
- pagos
- multi-tenant
- IA sofisticada
- ejecución real
- microservicios
- Kubernetes

---

# 37. Primer objetivo técnico

El primer milestone es:

## `M0 — Platform Discovery`

Responder:

```text
¿Cuál plataforma proporciona los mejores datos
para construir nuestro sistema?
```

Comparar:

```text
Invo
Hyperliquid
Bybit
Bitget
OKX
Binance
BingX
```

Crear una matriz:

| Capability | Invo | Hyperliquid | Bybit | Bitget | OKX |
|---|---|---|---|---|---|
| Trader discovery | ? | ? | ? | ? | ? |
| Trader history | ? | ? | ? | ? | ? |
| Positions | ? | ? | ? | ? | ? |
| Trades | ? | ? | ? | ? | ? |
| PnL | ? | ? | ? | ? | ? |
| ROI | ? | ? | ? | ? | ? |
| Drawdown | ? | ? | ? | ? | ? |
| API | ? | ? | ? | ? | ? |
| WebSocket | ? | ? | ? | ? | ? |
| Copy trading | ? | ? | ? | ? | ? |
| Automated execution | ? | ? | ? | ? | ? |
| Historical depth | ? | ? | ? | ? | ? |

No rellenar con suposiciones.

Cada celda debe tener evidencia de documentación oficial o una prueba real.

---

# 38. Segundo milestone

## `M1 — Data Pipeline`

Conectar una plataforma.

```text
API
 ↓
Collector
 ↓
Raw JSON
 ↓
Normalizer
 ↓
PostgreSQL
```

Debe ser posible ejecutar:

```bash
python -m collector.sync
```

y obtener datos reproducibles.

---

# 39. Tercer milestone

## `M2 — Trader Intelligence`

Crear:

```text
metrics/
scoring/
behavior/
```

Resultado:

```text
Trader
ROI
PnL
Drawdown
Sharpe
Consistency
BehaviorRisk
TraderScore
```

---

# 40. Cuarto milestone

## `M3 — Paper Trading`

Simular:

```text
Initial capital
Trader selection
Position sizing
Entry
Exit
Fees
Funding
Slippage
Drawdown
```

Y generar equity curve.

---

# 41. Quinto milestone

## `M4 — Validation`

Comparar:

```text
Buy & Hold BTC

vs

Top ROI Traders

vs

Top Sharpe Traders

vs

Top TraderScore

vs

TraderScore + Risk Management
```

Evaluar:

```text
ROI
CAGR
Max Drawdown
Sharpe
Sortino
Calmar
Win Rate
Profit Factor
Volatility
```

---

# 42. Criterio para avanzar a dinero real

No utilizar dinero real simplemente porque:

```text
"ganamos en el backtest"
```

Antes de hacerlo debemos demostrar:

```text
Backtest
     ↓
Out-of-sample
     ↓
Paper trading
     ↓
Live paper trading
     ↓
Small capital
```

Y comparar constantemente:

```text
Expected
vs
Actual
```

---

# 43. Métrica principal

No optimizar únicamente:

```text
ROI
```

La métrica principal debería ser:

```text
Risk-adjusted return
```

acompañada de:

```text
Maximum Drawdown
Probability of Ruin
Consistency
```

---

# 44. Cosas que NO debemos hacer

## NO

Crear un bot que simplemente:

```text
BUY cuando trader compra
SELL cuando trader vende
```

sin considerar:

- tamaño
- leverage
- riesgo
- slippage
- fees
- funding
- liquidez
- drawdown

## NO

Seleccionar traders por:

```text
Highest ROI
```

únicamente.

## NO

Confiar en un LLM para tomar todas las decisiones.

## NO

Meter dinero real durante el desarrollo.

## NO

Optimizar un modelo hasta que funcione perfectamente en datos históricos.

Eso puede producir overfitting.

---

# 45. Preguntas de investigación

Crear un archivo:

```text
docs/research/open-questions.md
```

con estas preguntas:

### Plataforma

- ¿Qué plataforma ofrece más datos?
- ¿Cuál tiene mayor profundidad histórica?
- ¿Cuál tiene API más estable?
- ¿Cuál permite automatización?
- ¿Cuál tiene menor costo?

### Traders

- ¿Cómo se calcula ROI?
- ¿Cómo se calcula PnL?
- ¿Cómo se calcula drawdown?
- ¿Podemos reconstruir equity curves?
- ¿Podemos obtener operaciones individuales?

### Trading

- ¿Cómo afectan fees?
- ¿Cómo afecta funding?
- ¿Cómo afecta slippage?
- ¿Qué ocurre con liquidaciones?
- ¿Cómo se replica una posición?

### Model

- ¿Qué métricas predicen mejor rendimiento futuro?
- ¿Cuánto histórico necesitamos?
- ¿Qué señales indican deterioro?
- ¿Qué comportamientos anticipan grandes pérdidas?

---

# 46. Research log

Toda decisión importante debe documentarse.

Formato:

```text
docs/decisions/

ADR-001-platform-selection.md
ADR-002-database.md
ADR-003-scoring-model.md
ADR-004-paper-trading.md
```

Nunca tomar decisiones importantes solamente dentro del código.

---

# 47. Principio de reproducibilidad

Todo resultado importante debe poder responder:

> ¿Por qué el sistema decidió esto?

Ejemplo:

```text
Trader X
Score: 82

¿Por qué?

Risk-adjusted return: 88
Consistency:          91
Drawdown:             84
Longevity:            77
Behavior risk:        71

Warnings:
- Increasing leverage
- High BTC concentration
```

---

# 48. Roadmap

```text
PHASE 0
Platform Research
       ↓
PHASE 1
Data Collection
       ↓
PHASE 2
Normalization
       ↓
PHASE 3
Trader Analytics
       ↓
PHASE 4
TraderScore
       ↓
PHASE 5
Backtesting
       ↓
PHASE 6
Paper Trading
       ↓
PHASE 7
Risk Engine
       ↓
PHASE 8
Live Monitoring
       ↓
PHASE 9
Small Capital
       ↓
PHASE 10
Optimization
```

---

# 49. Primera tarea para Codex/Claude

No pedirle inicialmente que construya el sistema completo.

Primero darle:

> Investiga las plataformas de copy trading definidas en `docs/platforms/`.
>
> Para cada plataforma identifica únicamente información verificable en documentación oficial.
>
> Determina:
>
> - APIs
> - endpoints relacionados con traders
> - historial
> - posiciones
> - trades
> - performance
> - WebSocket
> - copy trading
> - ejecución
> - rate limits
> - autenticación
> - restricciones
>
> No inventes endpoints.
>
> Cada afirmación debe incluir su fuente.
>
> No implementes todavía.
>
> Genera una matriz comparativa y recomienda qué plataforma deberíamos utilizar para el MVP basándote exclusivamente en disponibilidad de datos y capacidad de automatización.

---

# 50. Regla del proyecto

> **Primero datos. Después análisis. Después simulación. Después automatización. Finalmente dinero.**

Nunca invertir el orden.

---

# 51. Objetivo final

El sistema terminado debería poder responder automáticamente:

> "De todos los traders disponibles, ¿quiénes presentan actualmente la mejor combinación de rendimiento, consistencia y riesgo, cuánto capital deberíamos asignar a cada uno y cuándo deberíamos dejar de copiarlos?"

Ese es el verdadero producto.

No queremos construir simplemente un bot de trading.

Queremos construir un:

**AI-powered Trader Intelligence & Copy Trading System.**

---

# 52. Estado actual

```text
[ ] Crear repositorio
[ ] Crear documentación inicial
[ ] Investigar Invo
[ ] Investigar Hyperliquid
[ ] Investigar Bybit
[ ] Investigar Bitget
[ ] Investigar OKX
[ ] Investigar Binance
[ ] Investigar BingX

[ ] Seleccionar primera plataforma
[ ] Implementar collector
[ ] Diseñar PostgreSQL schema
[ ] Normalizar traders
[ ] Crear métricas
[ ] Crear TraderScore
[ ] Crear backtester
[ ] Crear paper trading
[ ] Crear risk engine
[ ] Crear dashboard

[ ] Validación out-of-sample
[ ] Paper trading prolongado
[ ] Evaluación de resultados
[ ] Decidir si utilizar capital real
```

---

## Nota de riesgo

Este proyecto es experimental y puede producir pérdidas financieras.

El objetivo inicial es desarrollar y validar software, no garantizar rentabilidad.

Ninguna métrica histórica garantiza resultados futuros.