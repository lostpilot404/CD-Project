import sys, json; sys.path.insert(0,'.'); sys.path.insert(0,'submission/tools/probes')
from battery_cases_1 import CASES
from codetrace.analysis.pipeline import analyse_source
ok=0; rows=[]
for name, expect, sinkline, src in CASES:
    p = analyse_source(src+"\n", filename="case.ctc")
    f = p.findings
    lines = [x.sink.get("line") for x in f]
    good = (len(f)==expect) and (sinkline is None or lines==[sinkline]*expect)
    ok += good
    rows.append((("PASS" if good else "FAIL"), name, expect, len(f), lines, [d.code for d in p.diagnostics], [x.certainty for x in f]))
for r in rows: print(f"{r[0]}  {r[1]:<62} expect={r[2]} got={r[3]} sink_lines={r[4]} cert={r[6]} diags={r[5]}")
print(f"\n{ok}/{len(CASES)} hand-labelled cases match")
