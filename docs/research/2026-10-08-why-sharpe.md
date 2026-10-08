# ¿Por qué solo Sharpe funciona? (pregunta abierta del 2026-10-07, respondida)

Hipótesis previa (research/2026-10-07-signal-family): Sortino, Calmar y bajo-drawdown seleccionan perfiles de cola oculta tipo martingala. Prueba: 281 traders con señales de 12 semanas y ≥ 5 operaciones en fills; comportamiento del top 20 % por cada señal (56 traders por grupo).

| Grupo | Martingala | Win rate | Dependencia del mejor trade | Con liquidación | Leverage p95 |
|---|---|---|---|---|---|
| todos | 0.43 | 61 % | 24 % | 28 % | 10.0x |
| **top Sharpe** | 0.42 | **66 %** | **13 %** | 30 % | 10.1x |
| top Sortino | 0.42 | 57 % | 27 % | **43 %** | 10.8x |
| top Calmar | 0.42 | 58 % | **31 %** | **41 %** | 10.8x |
| top bajo-DD | 0.42 | 66 % | 17 % | 27 % | 8.6x |

## Lectura

- **Martingala: rechazada.** Es igual en todos los grupos (~0.42).
- **Lo que sí distingue:** Sortino y Calmar eligen traders cuyas ganancias dependen de **una sola operación grande** (27-31 % del total vs 13 % en Sharpe), con menor win rate y **más liquidaciones** (41-43 % vs 30 %). Son perfiles "lotería": un gran acierto infla el retorno y el Sortino (que solo castiga las caídas) no ve que el resto es ruido. El Sharpe castiga la volatilidad en ambos sentidos, así que exige ganancias **repartidas** en muchas operaciones, que es lo que persiste.
- **Bajo-drawdown** no muestra patología de comportamiento; su falla es la otra que encontramos hoy: premia cuentas inactivas (drawdown 0), igual que los componentes del TraderScore v1.

## Advertencias

Muestra chica (56 por grupo) y sesgada hacia el universo rastreado (los únicos con fills). Indicativo, no concluyente. Con el embudo de candidatos los fills siguen creciendo; repetible con `/tmp/sortino_q.py` como base.

## Consecuencia para v2 (ya registrada en ADR-003)

Coherente con el diseño de la v2: ranking por Sharpe, exclusión de inactivos y de liquidados. Candidato adicional, anotado y **no adoptado**: excluir traders con dependencia del mejor trade > 30 %.
