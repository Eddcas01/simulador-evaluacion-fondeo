import json, sys
r = json.load(open(sys.argv[1]))
out = sys.argv[2]
b = r['scen']['base']
data = dict(
    seq=[dict(n=x['n'], s=x['start'], e=x['end'], r=x['res'], d=x['days'], c=x['cost'], det=x['det']) for x in b['seq']],
    daily=[dict(d=x['day'], mx=x['max'], mn=x['min'], r=x['res']) for x in r['daily']],
    eq=r['eq'],
    rdp=b['roll_days_pass'], rdf=b['roll_days_fail'],
    scen={k: dict(p=v['passes'], f=v['fails'], c=v['cost'], cpp=v['cost_per_pass'], rp=v['roll_pass'], rn=v['roll_n'])
          for k, v in r['scen'].items()},
    meta={k: r[k] for k in ['ntrades', 'ndays', 'ntradedays', 'tp', 'sl', 'other', 'net', 'comm', 'days_min_le_1000', 'first_sl', 'first', 'last']},
)
html = open(sys.argv[3], encoding='utf-8').read().replace('/*DATA*/null', json.dumps(data))
open(out, 'w', encoding='utf-8').write(html)
print('ok', out)
