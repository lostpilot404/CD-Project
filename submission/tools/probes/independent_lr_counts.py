# Independent LR(0)/LR(1) canonical + LALR-by-core counting, written from the
# textbook definitions, sharing no code with codetrace.frontend.grammar.
import sys; sys.path.insert(0,'.')
from codetrace.frontend.grammar_lang import build_language_grammar

def indep_counts(prods, start):
    # prods: list of (lhs, rhs tuple); index 0 is the augmented production
    aug = ("S'", (start,))
    P = [aug] + list(prods)
    nts = {l for l,_ in P}
    syms = {s for _,r in P for s in r}
    # nullable/first by naive fixed point (independent code)
    nullable=set(); changed=True
    while changed:
        changed=False
        for l,r in P:
            if l not in nullable and all(s in nullable for s in r): nullable.add(l); changed=True
    first={s:({s} if s not in nts else set()) for s in syms|nts}
    changed=True
    while changed:
        changed=False
        for l,r in P:
            for s in r:
                before=len(first[l]); first[l]|=first[s]
                if len(first[l])!=before: changed=True
                if s not in nullable: break
    def first_seq(seq, la):
        out=set()
        for s in seq:
            out|=first[s]
            if s not in nullable: return out
        return out|{la}
    def closure(I):
        I=set(I); work=list(I)
        while work:
            p,d,la=work.pop()
            r=P[p][1]
            if d<len(r) and r[d] in nts:
                for q,(l2,_) in enumerate(P):
                    if l2==r[d]:
                        for b in first_seq(r[d+1:], la):
                            it=(q,0,b)
                            if it not in I: I.add(it); work.append(it)
        return frozenset(I)
    def goto(I,X):
        mv={(p,d+1,la) for p,d,la in I if d<len(P[p][1]) and P[p][1][d]==X}
        return closure(mv) if mv else None
    def build(lr1):
        start_item = closure({(0,0,'$')}) if lr1 else closure({(0,0,None)})
        states=[start_item]; idx={start_item:0}; work=[start_item]
        while work:
            I=work.pop()
            for X in sorted({P[p][1][d] for p,d,_ in I if d<len(P[p][1])}):
                J=goto(I,X)
                if J is None: continue
                if lr1 is False:
                    pass
                if J not in idx: idx[J]=len(states); states.append(J); work.append(J)
        return states
    # canonical LR(1)
    can = build(True)
    # LR(0) (lookaheads dropped), counted by core
    def core(I): return frozenset((p,d) for p,d,_ in I)
    lr0_cores={}
    lr0_states=[]
    start0 = frozenset({(0,0)})
    # LR(0) closure without lookahead
    def closure0(K):
        K=set(K); work=list(K)
        while work:
            p,d=work.pop(); r=P[p][1]
            if d<len(r) and r[d] in nts:
                for q,(l2,_) in enumerate(P):
                    if l2==r[d] and (q,0) not in K: K.add((q,0)); work.append((q,0))
        return frozenset(K)
    s0=closure0(start0); seen={s0:0}; lst=[s0]; work=[s0]
    while work:
        K=work.pop()
        for X in sorted({P[p][1][d] for p,d in K if d<len(P[p][1])}):
            mv={(p,d+1) for p,d in K if d<len(P[p][1]) and P[p][1][d]==X}
            J=closure0(mv)
            if J not in seen: seen[J]=len(lst); lst.append(J); work.append(J)
    # LALR states = canonical LR(1) states merged by core
    lalr_cores = {core(I) for I in can}
    return len(can), len(lst), len(lalr_cores)

if __name__ == "__main__":
    # Expression grammar cross-check (Dragon 4.28)
    expr=[("E",("T","Ep")),("Ep",("PLUS","T","Ep")),("Ep",()),("T",("F","Tp")),("Tp",("STAR","F","Tp")),("Tp",()),("F",("LP","E","RP")),("F",("ID",))]
    print("expr grammar (canonical LR1, LR0, LALR-by-core):", indep_counts(expr,"E"))
    s2=[("S",("C","C")),("C",("c","C")),("C",("d",))]
    print("S->CC (expect 10 canonical, 7 LR0 cores(LR0 count), 7 LALR):", indep_counts(s2,"S"))
    lg = build_language_grammar()
    prods=[(p.lhs, tuple(p.rhs)) for p in lg.productions[1:]]
    print("CT-C grammar productions", len(prods)+1)
    print("CT-C (canonical LR1, LR0, LALR-by-core):", indep_counts(prods, lg.start_symbol))
