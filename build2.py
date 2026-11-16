import json, sys
r = json.load(open(sys.argv[1]))
D = {}
for lab, v in r.items():
    b = v['base']
    months = sorted(set([m['m'] for m in b['monthly']] + [m['m'] for m in v['edge']['monthly']]))
    mm = {m['m']: m for m in b['monthly']}
    cum, prog = 0.0, []
    for m in months:
        x = mm.get(m, dict(fees=0, pay=0)); cum += x['pay'] - x['fees']; prog.append(dict(m=m, v=round(cum, 2), fees=x['fees'], pay=x['pay']))
    roll = v['roll']; rr = v['roll_real']
    D[lab] = dict(qty=v['qty'], edge={k: v['edge'][k] for k in v['edge'] if k not in ('eq', 'monthly')},
                  edge_real=dict(exp=v['edge_real']['exp'], ci_n=v['edge_real']['ci_n'], net=v['edge_real']['net'], pf=v['edge_real']['pf']),
                  eq=v['edge']['eq'], prog=prog,
                  base={k: b[k] for k in b if k not in ('eval_list', 'monthly')},
                  minp={k: v['min'][k] for k in ('got_pay', 'first1000', 'npays', 'trader', 'net')},
                  real={k: v['real'][k] for k in ('passed', 'got_pay', 'first1000', 'npays', 'trader', 'net', 'fees')},
                  roll=dict(n=len(roll), p=sum(x['ev'] == 'PASS' for x in roll), pay=sum(x['pay'] for x in roll),
                            dpay=sorted(x['dpay'] for x in roll if x['pay']), pay_real=sum(x['pay'] for x in rr)))
html = open(sys.argv[3], encoding='utf-8').read().replace('/*DATA*/null', json.dumps(D))
open(sys.argv[2], 'w', encoding='utf-8').write(html)
print('ok')
