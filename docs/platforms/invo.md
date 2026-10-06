# Invo (InvoXYZ)

Estado: **posible capa de discovery**, no infraestructura. Última verificación: 2026-10-06.

## Lo que sabemos

- Plataforma de social/copy trading ("mimic trading") **construida sobre Hyperliquid**, con más de 170 pares de perpetuos.
- Enruta sus órdenes con el **builder code `INVO`**. En su momento reportó $1.49B de volumen en 30 días y 40,801 traders únicos, segundo lugar en volumen por builder code (detrás de Phantom).
  Fuente: https://cryptobriefing.com/invoxyz-surpasses-trust-wallet-hyperliquid-volume/
- DefiLlama la lista como `invo-perps`: https://defillama.com/protocol/invo-perps

Como opera sobre Hyperliquid, el track record "verificable" de sus traders debería corresponder a fills on-chain que podemos consultar directamente (ver [hyperliquid.md](hyperliquid.md)).

## Cómo ligar perfiles de Invo con wallets

Opción más prometedora: los **builder fills**. Hyperliquid publica a diario cada trade hecho con un builder code:

```
https://stats-data.hyperliquid.xyz/Mainnet/builder_fills/{builder_address}/{YYYYMMDD}.csv.lz4
```

Si conseguimos la **dirección del builder de Invo**, obtendríamos la lista de wallets que operan a través de Invo, sin scraping.

## Pendiente

- [ ] Dominio oficial y documentación (`invo.trade` no resuelve).
- [ ] Dirección 0x del builder `INVO`. Ideas: dashboards de builder codes (HyperTracker, DefiLlama) o hacer un trade de prueba y ver el builder en la orden.
- [ ] ¿Los perfiles públicos muestran la wallet?
- [ ] ¿Tiene API? ¿Términos de uso?
- [ ] ¿Cómo calcula su ROI/PnL/win rate?
- [ ] Disponibilidad desde México.
