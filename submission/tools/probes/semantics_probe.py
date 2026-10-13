import sys; sys.path.insert(0,'.')
from codetrace.analysis.pipeline import analyse_source
def run(name, src):
    p = analyse_source(src, filename="x.ctc")
    print("==", name)
    print("  diags:", [(d.code,d.severity,d.line,d.col,d.message[:90]) for d in p.diagnostics])
    print("  complete:", p.analysis_complete, p.partial_reasons)
    return p
p = run("same name, different scopes", """int main() {
  int x = 1;
  { int x = 2; x = x + 1; }
  x = 3;
  return x;
}""")
sem = p.semantic
syms = [s for s in getattr(sem,'symbols',[]) ] if hasattr(sem,'symbols') else None
print("  semantic attrs:", [a for a in dir(sem) if not a.startswith('_')][:30])
run("undeclared identifier", """int main() {
  int a = 1;
  a = b + 1;
  return a;
}""")
run("use after block ends", """int main() {
  { int inner = 4; }
  return inner;
}""")
run("redeclaration same scope", """int main() {
  int a = 1;
  int a = 2;
  return a;
}""")
run("shadowing global param", """int g = 5;
int f(int g) { return g; }
int main() { return g; }""")
run("type mismatch", """int main() {
  int a = "hello";
  return a;
}""")
run("call arity", """int add(int a, int b) { return a + b; }
int main() { int r = add(1); return r; }""")
run("unknown function call", """int main() { int r = mystery(3); return r; }""")
