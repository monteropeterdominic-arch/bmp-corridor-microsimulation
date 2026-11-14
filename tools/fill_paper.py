"""Fill SUMO placeholders in the revised paper from results.json (re-runnable)."""
import copy, json, sys
import docx
from docx.shared import Inches
from docx.oxml.ns import qn

SRC, OUT, RES = sys.argv[1], sys.argv[2], sys.argv[3]
FIG = RES.rsplit('/', 1)[0]
R = json.load(open(RES))
res, val = R['results'], R['validation']
d = docx.Document(SRC)

def plain_rpr(p):
    for r in p.runs:
        rpr = r._r.rPr
        if rpr is not None and rpr.find(qn('w:highlight')) is None:
            return copy.deepcopy(rpr)
    rpr = copy.deepcopy(p.runs[0]._r.rPr) if p.runs and p.runs[0]._r.rPr is not None else None
    if rpr is not None and rpr.find(qn('w:highlight')) is not None:
        rpr.remove(rpr.find(qn('w:highlight')))
    return rpr

def set_text(p, text, keep=0):
    rpr = plain_rpr(p) if keep == 0 else plain_rpr(type(p)(p._p, p._parent))
    runs = p.runs
    if keep:
        rpr = copy.deepcopy(runs[keep]._r.rPr) if runs[keep]._r.rPr is not None else rpr
        if rpr is not None and rpr.find(qn('w:highlight')) is not None:
            rpr.remove(rpr.find(qn('w:highlight')))
    for r in runs[keep:]:
        r._r.getparent().remove(r._r)
    r = p.add_run(text)
    if rpr is not None:
        r._r.insert(0, rpr)

def find(prefix):
    for p in d.paragraphs:
        if p.text.strip().startswith(prefix):
            return p
    raise KeyError(prefix)

def g(s, p, k):
    return res[s][p][k]
chg = lambda s, p, k='time_loss_s': res[s][p][k + '_chg_pct']
n_ok = sum(r['GEH'] < 5 for r in val['rows']); pct = val['pct_GEH_below_5']
words = {9: 'Nine', 10: 'Ten', 11: 'Eleven', 12: 'All twelve'}
singles = ['S1_tricycle_bay', 'S2_no_parking', 'S3_ctrl_crossing']
best = min(singles, key=lambda s: chg(s, 'morning'))
lab = {s: res[s]['morning']['label'] for s in res}
worst = max(val['rows'], key=lambda r: r['GEH'])

# abstract
p = find('Abstract')
t = p.text[len(p.runs[0].text):]
t = t.replace('[X]%', f'{pct:.0f}%').replace(
    '[the combined scenario reduced mean time loss per vehicle by X% and CO₂ emissions by X% in the morning peak]',
    f'the combined scenario reduced mean time loss per vehicle by {-chg("S4_combined","morning"):.0f}% and CO₂ '
    f'emissions by {-chg("S4_combined","morning","co2_kg"):.0f}% in the morning peak, with '
    f'{lab[best].lower()} the most effective single measure ({chg(best,"morning"):.0f}%)')
set_text(p, t, keep=1)

# validation text + table
sp = {k: g('S0_baseline', k, 'mid_speed_kph') for k in ('morning', 'midday', 'evening')}
set_text(find('Table 5 compares simulated'), (
    f'Table 5 compares simulated and observed 15-minute gate counts for the baseline (S0). '
    f'{words.get(n_ok, n_ok)} of the 12 intervals ({pct:.0f}%) achieved GEH < 5, '
    f'{"meeting" if pct >= 85 else "not meeting"} the 85% criterion (Figure 10). The largest deviation occurred in the '
    f'{worst["period"]} interval starting {worst["interval"]}, where the model released {worst["simulated"]:.0f} vehicles '
    f'against {worst["observed"]} observed (GEH = {worst["GEH"]:.1f}): the observed corridor discharged a surge of 442 '
    f'vehicles at 07:00–07:15 and then fell back, whereas the simulated corridor discharged more evenly, suggesting that '
    f'storage and release within the actual avenue are stronger than the model represents. Mean simulated speed on the '
    f'mid-segment was lowest in the morning peak ({sp["morning"]:.1f} km/h), followed by midday ({sp["midday"]:.1f} km/h) '
    f'and evening ({sp["evening"]:.1f} km/h), matching the order of the observed flow conditions. Because part of the '
    f'gate inflow was derived from the counts, this check mainly confirms that the coded network processes the observed '
    f'demand in the observed 15-minute pattern; independent validation with travel-time or speed data is recommended.'))

def table_after(caption_prefix):
    cap = find(caption_prefix)._p
    el = cap.getprevious()
    while el is not None and el.tag != qn('w:tbl'):
        el = el.getprevious()
    return docx.table.Table(el, d._body)

def cell(c, text):
    set_text(c.paragraphs[0], text)

t5 = table_after('Table 5. Observed versus')
for row, v in zip(t5.rows[1:], val['rows']):
    cell(row.cells[3], f'{v["simulated"]:.0f}'); cell(row.cells[4], f'{v["GEH"]:.1f}')
set_text(find('Table 5. Observed versus'), 'Table 5. Observed versus simulated 15-minute vehicle counts at the USM gate, '
         'baseline scenario S0 (simulated: mean of five seeds).')

order = ['S0_baseline', 'S1_tricycle_bay', 'S2_no_parking', 'S3_ctrl_crossing', 'S4_combined']
t6 = table_after('Table 6. Simulated performance')
sg = lambda x: f'{x:+.0f}'
for row, s in zip(t6.rows[1:], order):
    m, md = res[s]['morning'], res[s]['midday']
    cell(row.cells[1], f'{m["time_loss_s"]:.1f} ± {m["time_loss_s_sd"]:.1f}')
    cell(row.cells[3], f'{md["time_loss_s"]:.1f} ± {md["time_loss_s_sd"]:.1f}')
    if s == 'S0_baseline':
        for j in (2, 4, 5): cell(row.cells[j], '—')
    else:
        cell(row.cells[2], sg(chg(s, 'morning'))); cell(row.cells[4], sg(chg(s, 'midday')))
        cell(row.cells[5], sg(chg(s, 'morning', 'co2_kg')))
set_text(find('Table 6. Simulated performance'), 'Table 6. Simulated performance of the intervention scenarios '
         '(time loss: mean ± SD of five seeds; changes relative to S0).')

S1, S2, S3, S4 = singles + ['S4_combined']
set_text(find('Table 6 compares the intervention'), (
    f'Table 6 and Figure 11 compare the intervention scenarios with existing conditions. No-parking enforcement (S2) '
    f'was the most effective single measure, reducing mean time loss by {-chg(S2,"morning"):.0f}% in the morning peak '
    f'and {-chg(S2,"midday"):.0f}% at midday, followed by the tricycle loading bay (S1; {-chg(S1,"morning"):.0f}% and '
    f'{-chg(S1,"midday"):.0f}%). The controlled pedestrian crossing (S3) gave no benefit in the morning '
    f'({sg(chg(S3,"morning"))}%) and increased time loss at midday ({sg(chg(S3,"midday"))}%) and in the evening '
    f'({sg(chg(S3,"evening"))}%): at the observed pedestrian volumes, releasing pedestrians in fixed 12-s phases every '
    f'90 s stops traffic for longer in total than randomly arriving groups do, so a marshal-controlled crossing should '
    f'release pedestrians on demand rather than on a fixed cycle. Combining all three measures (S4) reduced mean time '
    f'loss by {-chg(S4,"morning"):.0f}% in the morning and {-chg(S4,"midday"):.0f}% at midday and cut peak-hour CO₂ '
    f'emissions by {-chg(S4,"morning","co2_kg"):.0f}% and {-chg(S4,"midday","co2_kg"):.0f}%, respectively; the maximum '
    f'number of halted vehicles in the morning fell from {g("S0_baseline","morning","max_halting"):.0f} to '
    f'{g(S4,"morning","max_halting"):.0f}. In the evening, when friction is low, no scenario improved performance. '
    f'Absolute delays are small ({g(S4,"morning","time_loss_s"):.0f}–{g("S0_baseline","morning","time_loss_s"):.0f} s '
    f'per vehicle in the morning) because the corridor is short, but they apply to more than 1,100 vehicles per peak '
    f'hour. Because total demand is identical across scenarios, differences in time loss and emissions are attributable '
    f'solely to the changed curbside and crossing behavior.'))

for prefix, img, w in [('[Insert results/fig_validation.png]', 'fig_validation.png', 2.6),
                       ('[Insert results/fig_time_loss.png]', 'fig_time_loss.png', 3.3)]:
    p = find(prefix)
    for r in p.runs:
        r._r.getparent().remove(r._r)
    p.add_run().add_picture(f'{FIG}/{img}', width=Inches(w))

set_text(find('Fifth, the calibrated SUMO model'), (
    f'Fifth, the calibrated SUMO model indicates that combining a tricycle loading bay, no-parking enforcement, and a '
    f'controlled crossing (S4) reduces mean time loss by {-chg(S4,"morning"):.0f}% and CO₂ emissions by '
    f'{-chg(S4,"morning","co2_kg"):.0f}% in the morning peak, with no-parking enforcement alone giving the largest single '
    f'reduction ({-chg(S2,"morning"):.0f}%). Low-cost curbside management can therefore substantially improve corridor '
    f'performance without road widening.'))
p = find('Based on the study')
set_text(p, p.text.replace('Recommendations 1–5 correspond to simulated scenarios S1–S4 (Table 6), and their priority '
                           'should follow the simulated reductions in delay.',
                           'The simulations (Table 6) indicate that no-parking enforcement should be the first priority, '
                           'followed by the tricycle loading bay, and that marshals at the USM gate should release '
                           'pedestrians on demand rather than on a fixed cycle.'))
d.save(OUT)
left = [p.text[:60] for p in d.paragraphs if '[' in p.text and ']' in p.text]
print('saved; remaining bracketed paragraphs:'); print('\n'.join(left))
