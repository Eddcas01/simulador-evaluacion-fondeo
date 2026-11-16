"""Ciclo completo LucidFlex 25K: evaluacion -> funded -> payouts, mas analisis de edge.
Uso: python sim2.py out.json etiqueta=csv [etiqueta=csv ...]
"""
import csv, json, sys, random, math
from datetime import datetime, date
from collections import OrderedDict, defaultdict

def money(s):
    return float(s.replace('$', '').replace('.', '').replace(',', '.').strip() or 0)

def load(path):
    tr = []
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f, delimiter=';'):
            if not r.get('Trade number'):
                continue
            et = datetime.strptime(r['Entry time'], '%d/%m/%Y %H:%M:%S')
            xt = datetime.strptime(r['Exit time'], '%d/%m/%Y %H:%M:%S')
            tr.append(dict(n=int(r['Trade number']), entry=et, exit=xt, day=et.date().isoformat(),
                           side=r['Market pos.'], qty=int(r['Qty']), pnl=money(r['Profit']),
                           comm=money(r['Commission']), mae=money(r['MAE']), mfe=money(r['MFE']),
                           ex=r['Exit name'], ep=money(r['Entry price']) if False else float(r['Entry price'].replace('.', '').replace(',', '.'))))
    tr.sort(key=lambda t: t['entry'])
    return tr

# ---------------- reglas ----------------
EVAL_TARGET, MLL, LOCK = 1250.0, 1000.0, 100.0   # piso deja de subir en +$100 (25,100)
CONS = 0.40
DLL, MIN_DAY, NDAYS, PAY_MAX, PAY_MIN, NPAY, SPLIT = 600.0, 100.0, 5, 1000.0, 500.0, 5, 0.90
FEE_NEW, FEE_RESET = 60.20, 60.0

class Ctx:
    def __init__(self, trades, extra=0.0):
        self.days = sorted(set(t['day'] for t in trades))
        self.by = defaultdict(list)
        for t in trades:
            self.by[t['day']].append(t)
        self.extra = extra

def run_eval(c, i0):
    bal = eod_high = 0.0
    dayp = {}
    for i in range(i0, len(c.days)):
        d = c.days[i]
        floor = min(eod_high - MLL, LOCK)
        dp = 0.0
        for t in c.by[d]:
            if bal + dp - t['mae'] - t['comm'] - c.extra <= floor + 1e-9:
                return 'FAIL', i
            dp += t['pnl'] - c.extra
            dayp[d] = dp
            tot = bal + dp
            if tot >= EVAL_TARGET and max(dayp.values()) <= CONS * tot + 1e-9:
                return 'PASS', i
        bal += dp
        eod_high = max(eod_high, bal)
    return 'OPEN', len(c.days) - 1

def run_funded(c, i0, policy='max'):
    """policy 'max': pide $1000 cuando 50% de la ganancia >= 1000. 'min': pide en cuanto pueda >= $500."""
    bal = eod_high = 0.0
    pays = []          # (dia, monto)
    pdays = 0; cyc0 = 0.0
    blown = None
    for i in range(i0, len(c.days)):
        d = c.days[i]
        floor = min(eod_high - MLL, LOCK)
        dll_on = floor < LOCK
        dp = 0.0
        for t in c.by[d]:
            adverse = t['mae'] + t['comm'] + c.extra
            to_floor = bal + dp - floor
            to_dll = dp + DLL if dll_on else 1e18
            if adverse >= min(to_floor, to_dll) - 1e-9:
                if to_dll < to_floor:          # DLL: cierra el dia en -600 (soft)
                    dp = -DLL
                    break
                blown = d
                break
            dp += t['pnl'] - c.extra
        bal += dp
        if blown:
            return dict(res='BLOWN', end=d, pays=pays, bal=bal)
        eod_high = max(eod_high, bal)
        if dp >= MIN_DAY:
            pdays += 1
        if pdays >= NDAYS and bal - cyc0 > 0:
            amt = min(0.5 * bal, PAY_MAX)
            if (policy == 'max' and amt >= PAY_MAX - 1e-9) or (policy == 'min' and amt >= PAY_MIN):
                pays.append((d, amt))
                bal -= amt; cyc0 = bal; pdays = 0
                if len(pays) >= NPAY:
                    return dict(res='LIVE', end=d, pays=pays, bal=bal)
    return dict(res='OPEN', end=c.days[-1], pays=pays, bal=bal)

def pipeline(c, policy='max'):
    """Una evaluacion a la vez; cada aprobada abre una funded que corre en paralelo."""
    i, evals, funded, cost, prev = 0, [], [], 0.0, None
    while i < len(c.days):
        fee = FEE_RESET if prev == 'FAIL' else FEE_NEW
        res, end = run_eval(c, i)
        cost += fee
        evals.append(dict(start=c.days[i], end=c.days[end], res=res, fee=fee, cost=round(cost, 2)))
        if res == 'PASS' and end + 1 < len(c.days):
            f = run_funded(c, end + 1, policy)
            f['start'] = c.days[end + 1]
            funded.append(f)
        prev = res
        i = end + 1
    # concurrencia maxima de funded vivas
    conc = 0
    for d in c.days:
        conc = max(conc, sum(1 for f in funded if f['start'] <= d <= f['end']))
    return evals, funded, cost, conc

def summarize(c, policy='max'):
    evals, funded, cost, conc = pipeline(c, policy)
    np_ = sum(1 for e in evals if e['res'] == 'PASS'); nf = sum(1 for e in evals if e['res'] == 'FAIL')
    allpays = [p for f in funded for p in f['pays']]
    got = [f for f in funded if f['pays']]
    gross = sum(a for _, a in allpays)
    # timeline mensual de cuotas y cobros
    mon = defaultdict(lambda: dict(fees=0.0, pay=0.0))
    for e in evals:
        mon[e['start'][:7]]['fees'] += e['fee']
    for d, a in allpays:
        mon[d[:7]]['pay'] += a * SPLIT
    return dict(evals=len(evals), passed=np_, failed=nf, fees=round(cost, 2), funded=len(funded),
                blown0=sum(1 for f in funded if f['res'] == 'BLOWN' and not f['pays']),
                blown_after=sum(1 for f in funded if f['res'] == 'BLOWN' and f['pays']),
                live=sum(1 for f in funded if f['res'] == 'LIVE'),
                open=sum(1 for f in funded if f['res'] == 'OPEN'),
                got_pay=len(got), first1000=sum(1 for f in funded if f['pays'] and f['pays'][0][1] >= 1000 - 1e-9),
                npays=len(allpays), pays_gross=round(gross, 2), trader=round(gross * SPLIT, 2),
                net=round(gross * SPLIT - cost, 2), conc=conc,
                paydist=[len(f['pays']) for f in funded],
                funded_list=[dict(s=f['start'], e=f['end'], r=f['res'], p=[[d, a] for d, a in f['pays']]) for f in funded],
                eval_list=evals,
                monthly=[dict(m=m, **v) for m, v in sorted(mon.items())])

def rolling(c, policy='max'):
    """Arrancando cada dia: prob. de aprobar y de llegar al primer cobro de $1000 con esa cuenta."""
    out = []
    for i in range(len(c.days)):
        res, end = run_eval(c, i)
        r = dict(start=c.days[i], ev=res, pay=False, dpay=None)
        if res == 'PASS' and end + 1 < len(c.days):
            f = run_funded(c, end + 1, policy)
            if f['pays']:
                r['pay'] = True
                r['dpay'] = c.days.index(f['pays'][0][0]) - i + 1
        out.append(r)
    return out

# ---------------- edge ----------------
def edge(trades, extra=0.0):
    days = sorted(set(t['day'] for t in trades))
    tp = [t for t in trades if t['ex'] == 'Profit target']; sl = [t for t in trades if t['ex'] == 'Stop loss']
    oth = [t for t in trades if t['ex'] not in ('Profit target', 'Stop loss')]
    tpv = sum(t['pnl'] + t['comm'] for t in tp) / len(tp); slv = -sum(t['pnl'] + t['comm'] for t in sl) / len(sl)
    p0 = slv / (slv + tpv)
    race = len(tp) / (len(tp) + len(sl))
    z = (race - p0) / math.sqrt(p0 * (1 - p0) / (len(tp) + len(sl)))
    net = [t['pnl'] - extra for t in trades]; gross = [t['pnl'] + t['comm'] for t in trades]
    byday = defaultdict(lambda: [0.0, 0.0, 0])
    for t in trades:
        b = byday[t['day']]; b[0] += t['pnl'] - extra; b[1] += t['pnl'] + t['comm']; b[2] += 1
    dl = list(byday.values())
    random.seed(7)
    bs_n, bs_g = [], []
    for _ in range(4000):
        s = [random.choice(dl) for _ in dl]
        nn = sum(x[2] for x in s)
        bs_n.append(sum(x[0] for x in s) / nn); bs_g.append(sum(x[1] for x in s) / nn)
    bs_n.sort(); bs_g.sort()
    ci = lambda a: (round(a[int(.025 * len(a))], 2), round(a[int(.975 * len(a))], 2))
    def side(sd):
        ts = [t for t in trades if t['side'] == sd]
        a = [t for t in ts if t['ex'] == 'Profit target']; b = [t for t in ts if t['ex'] == 'Stop loss']
        return dict(n=len(ts), net=round(sum(t['pnl'] - extra for t in ts), 2),
                    race=round(len(a) / max(1, len(a) + len(b)), 4),
                    exp=round(sum(t['pnl'] - extra for t in ts) / max(1, len(ts)), 2))
    eq, cum, peak, mdd = [], 0.0, 0.0, 0.0
    for d in days:
        cum += byday[d][0]; peak = max(peak, cum); mdd = min(mdd, cum - peak)
        eq.append(dict(d=d, v=round(cum, 2)))
    mon = defaultdict(float)
    for t in trades:
        mon[t['day'][:7]] += t['pnl'] - extra
    q = defaultdict(float)
    for t in trades:
        m = int(t['day'][5:7]); q[f"{t['day'][:4]}-T{(m - 1) // 3 + 1}"] += t['pnl'] - extra
    wins = sum(x for x in net if x > 0); loss = -sum(x for x in net if x < 0)
    return dict(n=len(trades), ndays=len(days), tp=len(tp), sl=len(sl), oth=len(oth), oth_net=round(sum(t['pnl'] for t in oth), 2),
                tpv=round(tpv, 2), slv=round(slv, 2), p0=round(p0, 4), race=round(race, 4), z=round(z, 2),
                net=round(sum(net), 2), exp=round(sum(net) / len(net), 2), exp_g=round(sum(gross) / len(gross), 2),
                ci_n=ci(bs_n), ci_g=ci(bs_g), pf=round(wins / loss, 3) if loss else None, mdd=round(mdd, 2),
                long=side('Long'), short=side('Short'), eq=eq,
                monthly=[dict(m=k, v=round(v, 2)) for k, v in sorted(mon.items())],
                quarters=[dict(q=k, v=round(v, 2)) for k, v in sorted(q.items())],
                pos_months=sum(1 for v in mon.values() if v > 0), n_months=len(mon),
                first_price=trades[0]['ep'], last_price=trades[-1]['ep'])

out = sys.argv[1]
res = {}
for arg in sys.argv[2:]:
    lab, path = arg.split('=', 1)
    tr = load(path)
    qty = tr[0]['qty']
    extra = 0.74 * qty           # comision "real": +$0.74 ida y vuelta por micro sobre la del backtest
    c = Ctx(tr); cr = Ctx(tr, extra)
    res[lab] = dict(qty=qty, edge=edge(tr), edge_real=edge(tr, extra),
                    base=summarize(c, 'max'), min=summarize(c, 'min'), real=summarize(cr, 'max'),
                    roll=rolling(c, 'max'), roll_real=rolling(cr, 'max'))
    b, e = res[lab]['base'], res[lab]['edge']
    rl = res[lab]['roll']
    print(f"== {lab} qty={qty}  n={e['n']} race={e['race']} p0={e['p0']} z={e['z']} exp={e['exp']} ci={e['ci_n']} gross ci={e['ci_g']} PF={e['pf']} mdd={e['mdd']} posM={e['pos_months']}/{e['n_months']}")
    print('   long', e['long'], ' short', e['short'], ' oth', e['oth'], e['oth_net'])
    for k in ('base', 'min', 'real'):
        s = res[lab][k]
        print(f"   [{k}] evals={s['evals']} pass={s['passed']} fail={s['failed']} fees={s['fees']} funded={s['funded']} blown0={s['blown0']} got_pay={s['got_pay']} first1000={s['first1000']} live={s['live']} open={s['open']} blown_after={s['blown_after']} npays={s['npays']} trader={s['trader']} net={s['net']} conc={s['conc']}")
    print('   rolling: pass', sum(r['ev'] == 'PASS' for r in rl), '/', len(rl), ' pay1000', sum(r['pay'] for r in rl),
          ' real pay', sum(r['pay'] for r in res[lab]['roll_real']))
    print('   quarters', [(x['q'], x['v']) for x in e['quarters']])
json.dump(res, open(out, 'w'), default=str)
