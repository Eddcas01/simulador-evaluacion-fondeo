# Simulador de evaluaciones de cuentas de fondeo

Simulador en **Python** que toma la lista de operaciones de un backtest de **NinjaTrader 8** y la reproduce
contra las reglas de una **cuenta de fondeo (prop firm) de 25K**. Calcula cuántas evaluaciones se aprueban o
se pierden, cuánto se gasta en cuotas y si la estrategia llega a cobrar. Los resultados se presentan en un
**reporte HTML interactivo** sin dependencias.

Responde una pregunta concreta: *con este historial de operaciones, ¿comprar evaluaciones es rentable o solo
quema cuotas?*

## Qué simula

**`sim.py`, solo la evaluación**
- Objetivo de **+$1 250**, **pérdida máxima trailing de $1 000 al cierre del día** (el piso sube con el saldo
  de cierre y se congela en el saldo inicial) y **regla de consistencia del 40 %** (el mejor día no puede
  superar el 40 % de la ganancia total).
- La pérdida intradía se mide con el **MAE** de cada operación, así que no basta con el cierre.
- Escenarios **secuencial** (cuenta nueva o reset tras perder, sumando cuotas) y **rolling** (una evaluación
  que empieza cada día del histórico, para no depender del día de inicio).

**`sim2.py`, el ciclo completo: evaluación → cuenta fondeada → cobros**
- Reglas de la fase fondeada: límite de pérdida diaria, días mínimos con ganancia, tope y mínimo por retiro,
  número de retiros y reparto 90/10.
- Políticas de retiro (`max` y `min`) y escenario de **comisiones reales** (+$0.74 por micro sobre las del
  backtest).
- **Análisis de edge**: compara la tasa de aciertos TP-vs-SL con la que daría el azar, `p0 = SL/(SL+TP)`,
  con un z-test. Calcula la expectativa por operación con **intervalo de confianza por bootstrap agrupado por
  días**, el factor de beneficio, el drawdown máximo y los resultados por trimestre y por mes.
- Acepta varias corridas a la vez (por ejemplo 2, 3 y 4 micros) para compararlas en el mismo reporte.

## Uso

Entrada: el CSV que exporta el **Strategy Analyzer → Trades** de NinjaTrader 8 (separado por `;`, formato
regional con coma decimal).

```bash
# Solo evaluación
python sim.py trades.csv log.txt resultado.json
python build.py resultado.json reporte.html plantillas/template.html

# Ciclo completo, varias corridas
python sim2.py resultado2.json 2micros=trades_2.csv 3micros=trades_3.csv
python build2.py resultado2.json reporte2.html plantillas/template2.html
```

Solo usa la **biblioteca estándar** de Python 3.10 o superior. Los reportes son un HTML autocontenido con
gráficos SVG dibujados a mano, tema claro/oscuro y tooltips.

## Ejemplos

En [`ejemplos/`](ejemplos) hay dos reportes generados con un backtest real de una estrategia de scalping en
MNQ. Descárgalos y ábrelos en el navegador.

## Tecnologías

Python (csv, json, statistics, bootstrap) · HTML/CSS/JS sin librerías · SVG
