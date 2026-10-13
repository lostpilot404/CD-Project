CASES2 = [
 ("Q1 sanitizer applied to a different variable does not clean c", 1, 4, """int main() {
  string c = input();
  string d = shell_escape("x");
  system(c);
  return 0;
}"""),
 ("Q2 compound assignment += propagates taint", 1, 4, """int main() {
  string c = "ls ";
  c += input();
  system(c);
  return 0;
}"""),
 ("Q3 sanitising helper function (interprocedural) cleans its return", 0, None, """string clean(string s) {
  return shell_escape(s);
}
int main() {
  string c = clean(input());
  system(c);
  return 0;
}"""),
 ("Q4 sink argument is a direct expression containing source", 1, 2, """int main() {
  system("ls " + input());
  return 0;
}"""),
 ("Q5 implicit flow via condition is NOT tracked (documented limitation)", 0, None, """int main() {
  string c = "ls";
  if (input() == "x") { c = "pwd"; }
  system(c);
  return 0;
}"""),
 ("Q6 same name in another function does not leak taint", 0, None, """int f() {
  string c = input();
  return 0;
}
int main() {
  string c = "ls";
  system(c);
  return 0;
}"""),
 ("Q7 comment-contained sink and source ignored", 0, None, """int main() {
  /* system(input());
     string c = input(); */
  system("date");
  return 0;
}"""),
 ("Q8 string literal containing a comment marker is not a comment", 1, 4, """int main() {
  string url = "http://x // not a comment";
  string c = input();
  system(c);
  return 0;
}"""),
 ("Q9 tainted then clean-only on the other path: may-flow stays", 1, 5, """int main() {
  string c = shell_escape(input());
  int k = input_int();
  if (k > 0) { c = input(); }
  system(c);
  return 0;
}"""),
 ("Q10 taint enters through a parameter of a helper that runs the sink", 1, 2, """int run(string cmd) {
  system(cmd);
  return 0;
}
int main() {
  run(input());
  return 0;
}"""),
 ("Q11 helper called only with a constant does not report", 0, None, """int run(string cmd) {
  system(cmd);
  return 0;
}
int main() {
  run("ls");
  return 0;
}"""),
 ("Q12 array element taint (whole-array attribution, documented)", 1, 4, """int main() {
  string arr[2];
  arr[0] = input();
  system(arr[1]);
  return 0;
}"""),
 ("Q13 loop may run zero times: documented over-approximation", 1, 5, """int main() {
  string c = input();
  int i = 0;
  while (i < 3) { c = "ls"; i = i + 1; }
  system(c);
  return 0;
}"""),
]
