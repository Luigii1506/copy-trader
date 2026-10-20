# ADR-004 — Ejecución real: espejo de una estrategia de papel, detrás de un guardia independiente

Fecha: 2026-10-20 · Estado: construido y probado con un exchange simulado; **sin credenciales, inactivo**

## Decisión

La ejecución real **no elige traders**. Replica en una cuenta real de Hyperliquid el portafolio de una estrategia del paper trading (por defecto `top_sharpe_pure`), escalado al capital de la cuenta. Toda la lógica de selección, riesgo y reglas de salida queda en `papertrade/`, ya probada en vivo. `execution/` solo traduce posiciones a órdenes (sección 16 del plan: la ejecución separada del análisis).

## Seguridad

- **Llave de agente (API wallet), nunca la llave principal.** Según la documentación oficial, firma operaciones de la cuenta principal pero **no puede retirar fondos** (sección 33 del plan). Se crea en app.hyperliquid.xyz/API.
- **La llave nunca entra al repositorio ni al backup:** vive en `~/data/copy-trader/secrets/hyperliquid_agent.json` con permisos 600. El sistema se niega a arrancar si el archivo es legible por otros usuarios. El backup de la laptop solo copia `raw/`, `universe/`, `state/`, el snapshot del paper trading y el dashboard.
- **Firma con el SDK oficial** (`hyperliquid-python-sdk` 0.24.0); no se reimplementa criptografía.
- **Doble seguro para operar:** hacen falta el archivo de credenciales **y** el flag `--live`. Sin `--live`, todo es simulación (dry run) y solo se registra.

## Guardia independiente (encima de los límites del paper trading)

| Límite | Valor inicial |
|---|---|
| Leverage bruto máximo sobre el capital real | 2x (el paper permite 5x por libro) |
| Orden máxima | $500 (lo que sobra se completa en los pasos siguientes) |
| Pérdida diaria | −5 % en el día UTC → cierra todo y se detiene |
| Mercados | solo el dex principal (HIP-3 después de probarlo aparte) |
| Slippage | órdenes IOC a mid ± 1 % (el SDK usa 5 % por defecto) |
| Kill switch | `copy-trader exec-halt`: cierra todo con órdenes reduce-only y queda detenido hasta borrar el archivo |

Cada orden intentada (enviada, simulada, rechazada o con error) queda en `~/data/copy-trader/execution/execution.db` con su motivo.

## Procedimiento para la red de pruebas (requiere al usuario)

1. **Requisito de Hyperliquid:** el faucet de testnet (1,000 USDC ficticios) solo da fondos a direcciones que **ya depositaron en mainnet** (app.hyperliquid-testnet.xyz/drip).
2. Crear una llave de agente para **testnet** en app.hyperliquid-testnet.xyz/API.
3. En la Studio, crear el archivo y protegerlo:
   ```bash
   mkdir -p ~/data/copy-trader/secrets && chmod 700 ~/data/copy-trader/secrets
   nano ~/data/copy-trader/secrets/hyperliquid_agent.json
   # {"network": "testnet", "account_address": "0x<cuenta principal>", "agent_secret_key": "0x<llave del agente>"}
   chmod 600 ~/data/copy-trader/secrets/hyperliquid_agent.json
   ```
4. `copy-trader exec-step`: simulación; muestra qué órdenes enviaría.
5. `copy-trader exec-step --live`: un paso real en testnet. Revisar con `copy-trader exec-status`.
6. `copy-trader exec-halt`: probar el kill switch.
7. Solo después, varios días de `exec-run --live` en testnet.

**Mainnet:** solo tras el veredicto del 2026-12-15, con el capital que el usuario decida, cambiando `network` a `mainnet` en el archivo. Esa decisión se registra aquí antes de ejecutarla.

## Probado

Exchange simulado (`tests/test_execution.py`): escalado de la cartera, idempotencia, que en dry run no se envíe nada, tope de leverage, tope por orden, kill switch reduce-only, alto por pérdida diaria y permisos del archivo de credenciales. Contra testnet real: lectura de mercados (156 mercados). **Falta, porque requiere credenciales:** enviar órdenes reales en testnet.
