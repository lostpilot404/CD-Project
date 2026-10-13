import sys; sys.path.insert(0,'.')
from codetrace.frontend.grammar import Grammar
from codetrace.frontend.clr_parser import build_tables

def G(start, prods, terms):
    g = Grammar(start_symbol=start)
    for lhs, rhs in prods: g.add(lhs, tuple(rhs))
    for t in terms: g.declare_terminal(t)
    return g.finalize()

# 1. Dragon book expression grammar: FIRST/FOLLOW/NULLABLE (Aho et al. 4.28)
expr = G("E", [("E",["T","Ep"]),("Ep",["PLUS","T","Ep"]),("Ep",[]),("T",["F","Tp"]),
               ("Tp",["STAR","F","Tp"]),("Tp",[]),("F",["LP","E","RP"]),("F",["ID"])],
         ["PLUS","STAR","LP","RP","ID"])
F = lambda s: set(expr.first[s]); FO = lambda s: set(expr.follow[s])
print("nullable", sorted(expr.nullable))
exp_first = {"E":{"LP","ID"},"Ep":{"PLUS"},"T":{"LP","ID"},"Tp":{"STAR"},"F":{"LP","ID"}}
exp_follow= {"E":{"$end","RP"},"Ep":{"$end","RP"},"T":{"PLUS","$end","RP"},"Tp":{"PLUS","$end","RP"},"F":{"STAR","PLUS","$end","RP"}}
ok=True
for s,v in exp_first.items():
    ok &= (F(s)==v); print("FIRST",s,sorted(F(s)), "OK" if F(s)==v else "MISMATCH expected "+str(sorted(v)))
for s,v in exp_follow.items():
    ok &= (FO(s)==v); print("FOLLOW",s,sorted(FO(s)), "OK" if FO(s)==v else "MISMATCH expected "+str(sorted(v)))
print("nullable expected {Ep,Tp}:", expr.nullable=={"Ep","Tp"})
t = build_tables(expr, mode="lalr"); print("expr lalr conflicts", len(t.conflicts), "states", len(t.automaton.states))
print("FIRST/FOLLOW all match textbook:", ok)

# 2. Dragon S -> C C, C -> c C | d : canonical LR(1) 10 states, LALR(1) 7 states
s2 = G("S",[("S",["C","C"]),("C",["c","C"]),("C",["d"])],["c","d"])
c2 = build_tables(s2,"canonical"); l2 = build_tables(s2,"lalr"); sl2 = build_tables(s2,"slr")
print("S->CC canonical states", len(c2.automaton.states), "conflicts", len(c2.conflicts))
print("S->CC lalr states", len(l2.automaton.states), "conflicts", len(l2.conflicts))
print("S->CC slr states", len(sl2.automaton.states), "conflicts", len(sl2.conflicts))

# 3. Dragon 4.55: S->aAd|bBd|aBe|bAe, A->c, B->c : LR(1) not LALR(1)
s3 = G("S",[("S",["a","A","d"]),("S",["b","B","d"]),("S",["a","B","e"]),("S",["b","A","e"]),("A",["c"]),("B",["c"])],["a","b","c","d","e"])
for m in ("canonical","lalr","slr"):
    t3 = build_tables(s3,m)
    print("LR(1)-not-LALR grammar", m, "conflicts", [(c.kind, c.terminal) for c in t3.conflicts], "states", len(t3.automaton.states))

# 4. Dangling-else / ambiguous expression under canonical too
amb = G("E",[("E",["E","PLUS","E"]),("E",["E","STAR","E"]),("E",["ID"])],["PLUS","STAR","ID"])
ta = build_tables(amb,"canonical"); print("ambiguous E grammar canonical conflicts:", len(ta.conflicts), sorted({c.kind for c in ta.conflicts}))
