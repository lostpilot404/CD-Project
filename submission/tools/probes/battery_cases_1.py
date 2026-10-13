# Hand-labelled taint battery. expect = number of findings, sink = line of
# the sink call that must carry the finding (None = no finding expected).
CASES = [
 ("P1 direct source->sink via variable", 1, 3, """int main() {
  string c = input();
  system(c);
  return 0;
}"""),
 ("P2 assignment chain a->b->c", 1, 5, """int main() {
  string a = input();
  string b = a;
  string c = b;
  system(c);
  return 0;
}"""),
 ("P3 propagation through concatenation expression", 1, 3, """int main() {
  string cmd = "ls " + input();
  system(cmd);
  return 0;
}"""),
 ("P4 branch merge: tainted on one path only", 1, 5, """int main() {
  int flag = input_int();
  string c = "ls";
  if (flag > 0) { c = input(); }
  system(c);
  return 0;
}"""),
 ("P5 loop-carried taint reaches sink in next iteration", 1, 4, """int main() {
  string c = "ls";
  int i = 0;
  while (i < 2) { system(c); c = input(); i = i + 1; }
  return 0;
}"""),
 ("P6 different sink: SQL with environment source", 1, 3, """int main() {
  string q = readenv("QUERY");
  sql_exec(q);
  return 0;
}"""),
 ("P7 path sink fopen via argv", 1, 3, """int main() {
  string p = argv(1);
  fopen(p, "r");
  return 0;
}"""),
 ("N1 strong update: constant redefinition kills taint", 0, None, """int main() {
  string c = input();
  c = "ls";
  system(c);
  return 0;
}"""),
 ("N2 independent variable is untainted", 0, None, """int main() {
  string u = input();
  string safe = "ls";
  system(safe);
  return 0;
}"""),
 ("N3 source never reaches sink", 0, None, """int main() {
  string u = input();
  system("ls");
  return 0;
}"""),
 ("N4 comment and string decoys are not code", 0, None, """int main() {
  // system(input());  <- commented out
  string s = "system(input())";
  system("date");
  return 0;
}"""),
 ("N5 configured sanitizer neutralises command taint", 0, None, """int main() {
  string c = shell_escape(input());
  system(c);
  return 0;
}"""),
 ("N6 sanitizer for a different context does not neutralise", 1, 4, """int main() {
  string c = input();
  string d = sql_escape(c);
  system(d);
  return 0;
}"""),
 ("N7 parse_to_int destroys text for all contexts", 0, None, """int main() {
  string n = input();
  int v = to_int(n);
  system(v);
  return 0;
}"""),
 ("N8 shadowed name: inner clean variable is the sink argument", 0, None, """int main() {
  string c = input();
  {
    string c = "ls";
    system(c);
  }
  return 0;
}"""),
 ("N9 sink in a branch literally never taken", 0, None, """int main() {
  string c = input();
  if (0) { system(c); }
  return 0;
}"""),
 ("N10 tainted value overwritten on every path before sink", 0, None, """int main() {
  string c = input();
  if (1 > 0) { c = "ls"; } else { c = "pwd"; }
  system(c);
  return 0;
}"""),
 ("P8 shadowed name: inner tainted variable is the sink argument", 1, 5, """int main() {
  string c = "ls";
  {
    string c = input();
    system(c);
  }
  return 0;
}"""),
 ("P9 two sinks, only one tainted", 1, 5, """int main() {
  string safe = "ls";
  string u = input();
  system(safe);
  system(u);
  return 0;
}"""),
]
