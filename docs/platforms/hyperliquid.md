# Hyperliquid

Estado: **plataforma elegida para el MVP de investigación** (ver [ADR-001](../decisions/ADR-001-hyperliquid-first.md)).
Última verificación: 2026-10-06.

Leyenda de evidencia: **[Doc]** documentación oficial · **[Prueba]** request real ejecutado el 2026-10-06 · **[No doc]** funciona, pero no está documentado.

## Resumen

Hyperliquid es un exchange de perpetuos on-chain. Toda la actividad de una wallet es pública: posiciones, fills y curva de capital. Por eso podemos **calcular nuestras propias métricas a partir de datos reales** en vez de confiar en un ROI publicado.

## Endpoints relevantes

Todos son `POST https://api.hyperliquid.xyz/info`, públicos y sin autenticación.

| Request `type` | Qué da | Límites | Evidencia |
|---|---|---|---|
| `clearinghouseState` | Posiciones abiertas, margen, valor de cuenta, leverage | — | [Prueba] (documentado en la subpágina de perpetuals) |
| `userFills` | Fills recientes | máx. 2000 más recientes | [Doc] |
| `userFillsByTime` | Fills por rango de tiempo (`startTime`, `endTime`) | 2000 por respuesta; "only the 10000 most recent fills are available" | [Doc] |
| `portfolio` | `accountValueHistory` y `pnlHistory` para day/week/month/allTime (y perp*) | serie submuestreada (~100-130 puntos) | [Doc] + [Prueba] |
| `historicalOrders` | Órdenes históricas | máx. 2000 | [Doc] |
| `vaultDetails` | Detalle de vaults (copy trading nativo de HL) | — | [Doc] |

Campos de un fill ([Prueba]): `coin, px, sz, side, time, startPosition, dir ("Open Long", "Close Short"...), closedPnl, hash, oid, tid, fee, feeToken, crossed, cloid, twapId`. Con `startPosition` + `sz` + `dir` se puede reconstruir el tamaño de la posición en cada momento.

### Leaderboard (fuente de discovery)

`GET https://stats-data.hyperliquid.xyz/Mainnet/leaderboard` **[No doc]**. Lo usa el frontend oficial.

- 2026-10-06: **47,374 wallets**, ~39 MB JSON (4.2 MB gzip).
- Por wallet: `ethAddress`, `accountValue`, `displayName` y `windowPerformances` con `pnl/roi/vlm` para `day/week/month/allTime`.
- No consume peso del rate limit de la API (es otro host).
- Riesgo: puede cambiar o desaparecer sin aviso.

## Rate limits [Doc]

- REST: **1200 de peso por minuto por IP**, agregado.
- Peso 2: `l2Book, allMids, clearinghouseState, orderStatus, spotClearinghouseState, exchangeStatus`.
- Peso 60: `userRole`. Peso 20: el resto.
- Peso adicional de +1 por cada 20 items devueltos en `userFills`, `userFillsByTime`, `historicalOrders`, `userFunding`, `fundingHistory` y otros.
- WebSocket: 10 conexiones, 1000 suscripciones y **máx. 10 usuarios únicos** en suscripciones por usuario. No sirve para seguir cientos de wallets en tiempo real; para eso hay que hacer polling.

El collector usa 1000/min para dejar margen.

## Hallazgos de la primera prueba (2026-10-06)

1. **El límite de 10k fills no es exacto.** Una wallet devolvió 11,578 fills desde 2023-11. Hay que investigar si el límite cuenta otra cosa (¿fills agregados? ¿órdenes?).
2. **El `accountValue` del leaderboard no coincide con `clearinghouseState`.** En una wallet, el leaderboard daba ~63M y `clearinghouseState.marginSummary.accountValue` ~8.9k. Hipótesis: el leaderboard incluye spot, vaults y staking. **No usar el ROI del leaderboard sin entender cómo se calcula.**
3. **`portfolio.allTime` da una curva de capital de toda la historia de la wallet.** Esto permitiría un primer análisis de persistencia retroactivo sin esperar 90 días (cuidado con el sesgo de supervivencia: solo vemos wallets que hoy siguen en el leaderboard).
4. Paginar con "último timestamp como siguiente `startTime`" (recomendado por la doc) devuelve duplicados en el mismo milisegundo. Se deduplican por `(tid, oid)`.

## Builder codes (vínculo con Invo)

Los trades que usan un builder code se publican a diario [Doc]:
`https://stats-data.hyperliquid.xyz/Mainnet/builder_fills/{builder_address}/{YYYYMMDD}.csv.lz4` (dirección en minúsculas).

## Restricciones / ToS

- Pendiente de verificar: restricciones geográficas (México), términos de uso de la API y del endpoint de leaderboard.

## Fuentes

- Info endpoint: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- Rate limits: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- Builder codes: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/builder-codes

## Notas para el análisis

- Las wallets con más valor del leaderboard (~$1B) probablemente sean vaults o direcciones del protocolo (p. ej. HLP), no traders. Hay que identificarlas y excluirlas del estudio de persistencia.
- Mercados HIP-3 (perpetuos creados por terceros, incluidos los de acciones): varios endpoints aceptan `dex`. Hoy el collector solo consulta el mercado principal, así que las posiciones en HIP-3 podrían faltar. Pendiente de verificar.
