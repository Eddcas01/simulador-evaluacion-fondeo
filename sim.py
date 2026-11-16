"""Simula evaluaciones 25K Flex sobre los trades del backtest C3 15s.
Reglas: target +1250, max loss 1000 EOD trailing (piso = max saldo de cierre - 1000,
se congela en el saldo inicial), consistencia 40% (mejor dia <= 40% de la ganancia total),
sin daily loss limit. Pasa en cuanto la ganancia cerrada >= target y la consistencia se cumple
(se deja de operar ese mismo dia). Falla si la equity intradia (usando MAE) toca el piso.
"""
import csv, json, sys, re
from datetime import datetime
from collections import OrderedDict

CSV, LOG, OUT = sys.argv[1], sys.argv[2], sys.argv[3]

def money(s):
    return float(s.replace('$', '').replace('.', '').replace(',', '.').strip() or 0)

trades = []
with open(CSV, encoding='utf-8-sig') as f:
    for r in csv.DictReader(f, delimiter=';'):
        if not r.get('Trade number'):
            continue
        et = datetime.strptime(r['Entry time'], '%d/%m/%Y %H:%M:%S')
        xt = datetime.strptime(r['Exit time'], '%d/%m/%Y %H:%M:%S')
        trades.append(dict(n=int(r['Trade number']), entry=et, exit=xt, day=et.date().isoformat(),
                           pnl=money(r['Profit']), comm=money(r['Commission']),
                           mae=money(r['MAE']), mfe=money(r['MFE']), exitname=r['Exit name']))
trades.sort(key=lambda t: t['entry'])
overlaps = sum(1 for a, b in zip(trades, trades[1:]) if b['entry'] < a['exit'])

# log: max/min/resultado por dia
logdays = OrderedDict()
for line in open(LOG, encoding='utf-8', errors='replace'):
    m = re.match(r'DIA (\S+) \| max=([+\-\d,]+) \| min=([+\-\d,]+) \| resultado=([+\-\d,]+)', line)
    if m:
        f_ = lambda s: float(s.replace(',', '.'))
        logdays[m.group(1)] = dict(max=f_(m.group(2)), min=f_(m.group(3)), res=f_(m.group(4)))
days = list(logdays.keys())  # todos los dias de sesion (incluye dias sin trades)
bydaytr = OrderedDict((d, []) for d in days)
for t in trades:
    bydaytr.setdefault(t['day'], []).append(t)
days = sorted(bydaytr.keys())

TARGET, MAXLOSS = 1250.0, 1000.0

def run_eval(start_idx, cons=0.40, extra_comm=0.0, lock_at_start=True, f=1.0):
    """Devuelve (resultado, idx_dia_fin, dias_operados, detalle)."""
    bal = 0.0              # ganancia respecto a 25k
    eod_high = 0.0
    daypnl = {}
    traded = 0
    for i in range(start_idx, len(days)):
        d = days[i]
        floor = eod_high - MAXLOSS
        if lock_at_start:
            floor = min(floor, 0.0)
        dp = 0.0
        tl = bydaytr[d]
        if tl:
            traded += 1
        for t in tl:
            pnl = t['pnl'] * f - extra_comm
            worst = bal + dp - t['mae'] * f - t['comm'] * f - extra_comm
            if worst <= floor + 1e-9:
                return 'FAIL', i, traded, dict(day=d, trade=t['n'], bal=bal + dp, floor=floor)
            dp += pnl
            daypnl[d] = dp
            tot = bal + dp
            if tot >= TARGET:
                best = max(daypnl.values())
                if best <= cons * tot + 1e-9:
                    return 'PASS', i, traded, dict(day=d, trade=t['n'], profit=tot, best=best)
        bal += dp
        eod_high = max(eod_high, bal)
    return 'OPEN', len(days) - 1, traded, dict(bal=bal)

def sequential(cons=0.40, extra_comm=0.0, fee_new=60.20, fee_reset=60.0, f=1.0):
    i, seq, cost = 0, [], 0.0
    prev = None
    while i < len(days):
        # saltar dias sin trades para el arranque
        while i < len(days) and not bydaytr[days[i]]:
            i += 1
        if i >= len(days):
            break
        fee = fee_reset if prev == 'FAIL' else fee_new
        res, end, nd, det = run_eval(i, cons, extra_comm, f=f)
        cost += fee
        seq.append(dict(n=len(seq) + 1, start=days[i], end=days[end], res=res, days=nd, fee=fee, cost=round(cost, 2), det=det))
        prev = res
        i = end + 1
    return seq

def rolling(cons=0.40, extra_comm=0.0, f=1.0):
    out = []
    for i, d in enumerate(days):
        if not bydaytr[d]:
            continue
        res, end, nd, det = run_eval(i, cons, extra_comm, f=f)
        out.append(dict(start=d, res=res, days=nd, end=days[end]))
    return out

scen = {}
for key, cons, xc, f in [('base', 0.40, 0.0, 1.0), ('c50', 0.50, 0.0, 1.0), ('comm', 0.40, 3.70, 1.0), ('q4', 0.40, 0.0, 0.8)]:
    s = sequential(cons, xc, f=f)
    r = rolling(cons, xc, f=f)
    p = sum(1 for x in s if x['res'] == 'PASS'); fl = sum(1 for x in s if x['res'] == 'FAIL')
    rp = [x for x in r if x['res'] == 'PASS']; rf = [x for x in r if x['res'] == 'FAIL']
    scen[key] = dict(seq=s, roll=r, passes=p, fails=fl, open=sum(1 for x in s if x['res'] == 'OPEN'),
                     cost=s[-1]['cost'] if s else 0, cost_per_pass=(s[-1]['cost'] / p) if p else None,
                     roll_pass=len(rp), roll_fail=len(rf), roll_n=len(r),
                     roll_days_pass=sorted(x['days'] for x in rp), roll_days_fail=sorted(x['days'] for x in rf))

# Analisis diario: SL ($1005 > $1000) -- cuantos dias tienen minimo intradia <= -1000 segun log
sl = [t for t in trades if t['exitname'] == 'Stop loss']
daily = [dict(day=d, **logdays[d]) for d in logdays]
# equity curve por dia (cerrado)
eq, c = [], 0.0
for d in days:
    c += sum(t['pnl'] for t in bydaytr[d]); eq.append(dict(day=d, eq=round(c, 2)))
# primer trade del dia SL (muerte segura sin colchon intradia)
first_sl = sum(1 for d in days if bydaytr[d] and bydaytr[d][0]['exitname'] == 'Stop loss')
res = dict(ntrades=len(trades), overlaps=overlaps, ndays=len(days), ntradedays=sum(1 for d in days if bydaytr[d]),
           tp=sum(1 for t in trades if t['exitname'] == 'Profit target'), sl=len(sl),
           other=sum(1 for t in trades if t['exitname'] not in ('Profit target', 'Stop loss')),
           net=round(sum(t['pnl'] for t in trades), 2), comm=round(sum(t['comm'] for t in trades), 2),
           sl_loss=sl[0]['pnl'] if sl else None, mae_sl=max(t['mae'] for t in sl) if sl else None,
           days_min_le_1000=sum(1 for x in daily if x['min'] <= -1000), first_sl=first_sl,
           daily=daily, eq=eq, scen=scen, first=days[0], last=days[-1])
json.dump(res, open(OUT, 'w'), default=str)
for k, v in scen.items():
    print(k, 'pass', v['passes'], 'fail', v['fails'], 'open', v['open'], 'cost', round(v['cost'], 2), 'cpp', v['cost_per_pass'],
          '| rolling', v['roll_pass'], '/', v['roll_n'])
print({k: res[k] for k in ['ntrades', 'overlaps', 'ndays', 'ntradedays', 'tp', 'sl', 'other', 'net', 'comm', 'sl_loss', 'mae_sl', 'days_min_le_1000', 'first_sl']})
for x in scen['base']['seq'][:0]:
    print(x['n'], x['start'], x['end'], x['res'], x['days'], x['det'])
