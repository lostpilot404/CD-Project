import sys; sys.path.insert(0,'.')
from codetrace.analysis.pipeline import analyse_source
def show(src, fn="main"):
    p = analyse_source(src, filename="x.ctc")
    print("== diag:", [(d.code,d.line,d.message[:70]) for d in p.diagnostics], "complete:", p.analysis_complete, p.partial_reasons)
    cfg = p.cfgs[fn]
    for b in cfg.sorted_blocks():
        print("  B%d %-11s stmts=%s succ=%s" % (b.id, b.kind, b.statement_ids, [(e.dst,e.kind) for e in b.successors]))
    print("  reachable", sorted(cfg.reachable), "unreachable", sorted(cfg.unreachable), "loops", [(l.header,l.body_entry,l.break_target,l.continue_target) for l in cfg.loops])
    return p
print("A: if/else merge + early return")
show("""int f(int x) {
  int y = 0;
  if (x > 0) { y = 1; } else { y = 2; }
  if (y == 1) { return 5; }
  return y;
}""", "f")
print("B: break/continue")
show("""int main() {
  int i = 0;
  while (i < 10) {
    i = i + 1;
    if (i == 3) { continue; }
    if (i == 7) { break; }
  }
  return i;
}""")
print("C: code after return is unreachable")
show("""int main() {
  int x = 1;
  return x;
  x = 2;
}""")
print("D: for loop")
show("""int main() {
  int s = 0;
  for (int i = 0; i < 5; i = i + 1) { s = s + i; }
  return s;
}""")
