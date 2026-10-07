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
- **Mercados HIP-3** (perpetuos creados por terceros): `perpDexs` lista 10 además del principal (2026-10-06: `xyz, flx, vntl, hyna, km, abcd, cash, para, mkts, io`). `xyz` tiene perpetuos de acciones e índices (MU, SNDK, XYZ100, SILVER…). Los **fills y `portfolio` ya incluyen HIP-3** (coins con prefijo, p. ej. `xyz:MU`), pero **`clearinghouseState` es por dex**: 5 de 40 wallets del universo tenían posiciones abiertas en `xyz` invisibles desde el dex principal. Desde 2026-10-06 el collector consulta todos los dex.
- **Fees** [Doc]: nivel base perps 0.045 % taker / 0.015 % maker, con tiers por volumen de 14 días. HIP-3 puede tener fees distintas (fee share del deployer, "growth mode").
- **Funding** [Doc]: se paga **cada hora**; pago = `tamaño × precio oráculo × tasa` (1/8 de la tasa calculada a 8 h).
- **Resolución de `portfolio`:** ~70-110 puntos por wallet sin importar la antigüedad. Historias largas → un punto cada ~14 días; cortas → ~7 días o menos. El análisis usa pasos de 2 semanas por eso (ver `analysis/persistence.py`).
- **`perpAllTime` vs `allTime`:** ~25 % de las wallets muestran cuenta perp ≈ 0 casi siempre (guardan colateral fuera de perp). Para retornos usamos `allTime` (capital total).
- **Vaults** (`GET stats-data.hyperliquid.xyz/Mainnet/vaults`) **[No doc]**: 9,476 vaults (3,091 abiertas) con líder, TVL, APR y estado. Son el copy trading nativo de Hyperliquid (un líder opera con depósitos de seguidores) y candidatas para el "modelo A". 708 direcciones del leaderboard son vaults; se excluyen del estudio de traders. Las ~10 cuentas más grandes del leaderboard (~$0.2-1B) **no** son vaults: probablemente market makers o instituciones.
