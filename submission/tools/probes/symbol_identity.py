import sys; sys.path.insert(0,'.')
from codetrace.analysis.pipeline import analyse_source
src = """int main() {
  int x = 1;
  { int x = 2; x = x + 1; }
  x = 3;
  return x;
}"""
p = analyse_source(src, filename="x.ctc")
sem = p.semantic
for s in sem.symbols.values() if isinstance(sem.symbols, dict) else sem.symbols:
    print(s.__dict__ if hasattr(s,'__dict__') else s)
print("symbol_of keys:", list(sem.symbol_of.items())[:20] if isinstance(sem.symbol_of, dict) else sem.symbol_of)
cfg = p.cfgs["main"]
print("defs:", [(d.id, d.symbol_id, d.sid) for d in cfg.definitions])
