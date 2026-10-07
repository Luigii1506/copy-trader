# copy-trader

Investigación: ¿el rendimiento/riesgo pasado de un trader de Hyperliquid predice su rendimiento futuro?
Ver [proyect.md](proyect.md) (visión completa), [ADR-001](docs/decisions/ADR-001-hyperliquid-first.md) (alcance actual) , [ROADMAP](docs/ROADMAP.md) (estado y siguientes pasos) y [cómo funciona](docs/architecture/how-it-works.md) (qué decide el sistema, fases, dónde entra la IA).

## Uso

```bash
uv sync
uv run python -m collector.sync leaderboard   # snapshot del leaderboard + refresca universo (1×/día)
uv run python -m collector.sync wallets       # estado, portfolio y fills nuevos de cada wallet rastreada
uv run python -m collector.sync all           # ambos
uv run python -m collector.sync normalize     # crudo -> Parquet
uv run python -m collector.sync health        # ¿los jobs corren a tiempo? exit 1 si no
```

## Ejecución automática (launchd)

Corre en la Mac Studio (`admin@admins-mac-studio` por Tailscale), repo en `~/copy-trader`. Desplegar cambios: `git pull && ./scripts/install_launchd.sh`.

```bash
./scripts/install_launchd.sh    # instala `copy-trader` con uv tool y registra los jobs; re-ejecutar tras cambiar código
```

| Job | Horario (local) | Qué hace |
|---|---|---|
| `leaderboard` | cada hora | revisa si hay versión nueva del leaderboard; guarda máx. 1 cada 6 h (+ vaults) y refresca universo |
| `wallets` | 02:30 08:30 14:30 18:30 | estado, portfolio y fills nuevos |
| `normalize` | 04:15 19:45 | crudo → Parquet |
| `census` | manual | curvas de capital de ~43k traders del leaderboard (una vez, reanudable) |
| `papertrade` | siempre (KeepAlive) | motor de paper trading ([ADR-002](docs/decisions/ADR-002-paper-trading.md)) |

- Prioridad baja de CPU/IO, `caffeinate -i` durante la corrida y un lock por job (si sigue corriendo, la siguiente se salta).
- Si la Mac está dormida a la hora programada, el job corre una vez al despertar. **Con la tapa cerrada la Mac duerme y no recolecta.**
- Logs: `~/data/copy-trader/logs/<job>.log` · Correr ya: `launchctl kickstart gui/$(id -u)/com.luisencinas.copytrader.<job>`
- Código y datos de launchd viven fuera de `~/Documents` (macOS bloquea esa carpeta a launchd sin Full Disk Access).

### Backup y alertas (laptop)

```bash
./scripts/install_backup_laptop.sh   # cada 3h (si la laptop está despierta): copia raw/universe/state de la Studio
```

Copia a `~/data/copy-trader-backup` y ejecuta `copy-trader health` en la Studio. Si algo falla (job atrasado, >10% de wallets con error, poco disco o la Studio no responde) aparece una notificación de macOS. Log: `~/data/copy-trader-backup.log`.

## Desarrollo

```bash
uv sync --all-groups     # incluye research (DuckDB, Jupyter) y dev (pytest)
uv run pytest
```

## Paper trading

```bash
copy-trader papertrade-status    # equity, retorno, drawdown y leverage por estrategia
copy-trader papertrade-halt      # kill switch: cierra todas las posiciones simuladas y detiene
```

Estado y auditoría en `~/data/copy-trader/papertrade/papertrade.db` (SQLite): tablas `strategies`, `books`, `positions`, `events` (cada operación con su motivo) y `equity`.

## Datos

En `~/data/copy-trader` (`data/` en el repo es un symlink). Se puede cambiar con `COPY_TRADER_DATA=/ruta`.

```
data/raw/hyperliquid/<dataset>/date=YYYY-MM-DD/<run>.jsonl.gz   respuestas crudas con envelope
data/processed/hyperliquid/<tabla>/date=.../<run>.parquet       leaderboard, vaults, account_snapshots, positions, equity_history, fills
data/universe/hyperliquid.json                                  wallets rastreadas (append-only)
data/state/hyperliquid_fills_cursor.json                        cursor de fills por wallet
```

Consulta con DuckDB: `read_parquet('data/processed/hyperliquid/fills/*/*.parquet', union_by_name=true)`.
Fills y equity_history se repiten entre corridas: deduplicar por `(user, tid, oid)` y `(user, period, time_ms)`.
