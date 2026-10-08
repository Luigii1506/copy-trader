# Vaults y OKX: intentos de replicación (2026-10-08)

Misma metodología congelada (12 sem → 4 sem, mismos selectores y TraderScore). Scripts: `scripts/vault_study.py`, `scripts/okx_study.py`.

## Vaults de Hyperliquid (227 vaults, 2023-03 → 2026-09, neto de 10 % de comisión)

| Señal | IC | t-stat |
|---|---|---|
| sharpe | 0.031 | 0.7 |
| ret | 0.014 | 0.3 |
| pnl_usd | −0.002 | 0.0 |
| low_dd | −0.019 | −0.4 |
| random | −0.006 | −0.2 |

**Sin persistencia.** Ninguna señal distingue vaults buenas de malas. En el backtest, top_score (+52 %/año) queda dentro del rango del azar (random p90 +53 %), y top_sharpe da +6.5 %.

**Sesgo fuerte:** la lista son vaults abiertas *hoy* con ≥ $10k; las que cerraron o se vaciaron no están en el histórico. Por eso "todas las vaults" (+28 %/año, DD −12 %) está inflado y no debe leerse como rendimiento esperado. La lista solo-crece corrige esto **de aquí en adelante**.

**Conclusión:** con la evidencia actual, las vaults no son un mejor vehículo; nuestras señales no las seleccionan.

## OKX Copy Trading (254 lead traders, 1 año, 10 periodos)

| Señal | IC OKX | IC Hyperliquid | t-stat OKX |
|---|---|---|---|
| sharpe | **0.078** | 0.089 | 1.2 |
| pnl_usd | 0.039 | 0.100 | 0.5 |
| ret | 0.036 | 0.121 | 0.4 |
| low_dd | −0.042 | 0.159 | −0.5 |
| random | 0.001 | 0.000 | 0.0 |

- **Sharpe tiene el mismo signo y casi la misma magnitud que en Hyperliquid**, pero con 10 periodos el t-stat (1.2) no es significativo. Consistente, no concluyente.
- low_dd vuelve a fallar como selector (como en la prueba de familia de Hyperliquid).
- **El backtest no es interpretable:** el trader promedio rinde +59 %/año con −0.8 % de caída y el azar +53 %. Ese universo es casi puro sesgo de supervivencia: OKX solo lista a los líderes **actuales**; los que fracasaron dejaron de liderar y desaparecieron. Además el PnL lo calcula OKX y no sabemos cómo trata depósitos.

**Conclusión:** OKX ni confirma ni refuta. Las fotos diarias desde hoy registrarán a quién desaparece; en ~3-6 meses habrá una prueba OKX sin sesgo de supervivencia.

## Estado de la evidencia

| Evidencia | Resultado |
|---|---|
| Hyperliquid, 20k traders | Persistencia sí; top_sharpe +42 % |
| Hyperliquid, 41k traders (replicación) | Persistencia idéntica; top_sharpe +54 %, beta 0 |
| Vaults | Sin señal (universo chico y sesgado) |
| OKX | Sharpe mismo signo, no significativo; backtest sesgado |
| Forward (paper trading + leaderboard) | En curso; veredicto 2026-12-01 |

La evidencia principal sigue siendo Hyperliquid, que es justo el universo con mejores datos (on-chain, incluye perdedores). La replicación externa aún no la fortalece; tampoco la contradice. El forward congelado sigue siendo el juez.
