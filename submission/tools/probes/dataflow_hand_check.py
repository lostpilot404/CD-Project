import sys; sys.path.insert(0,'.')
from codetrace.analysis.pipeline import analyse_source
src = """int main() {
  int a = 1;
  int b = 2;
  while (a > 0) {
    b = a + b;
    a = a - 1;
  }
  return b;
}
"""
p = analyse_source(src, filename="df.ctc")
print("diagnostics:", [(d.code,d.message) for d in p.diagnostics], "complete:", p.analysis_complete)
cfg = p.cfgs["main"]
for b in cfg.sorted_blocks():
    print("B%d kind=%s stmts=%s succ=%s" % (b.id, b.kind, b.statement_ids, [(e.dst,e.kind) for e in b.successors]))
print("loops", [l.to_json() for l in cfg.loops])
print("defs", [(d.id, d.symbol_id, getattr(d,'name',None), getattr(d,'sid',None)) for d in cfg.definitions])
fa = p.analyses["main"]
print("reaching_states (sid->in/out def sets?):", fa.reaching_states)
print("live_states:", fa.live_states)
print("reaching_result attrs:", [a for a in dir(fa.reaching_result) if not a.startswith('_')])
