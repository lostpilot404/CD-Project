import json, urllib.request, urllib.error
B='http://127.0.0.1:8000'
def call(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(B+path, data=data, method=method, headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req) as r: return r.status, r.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()
def summ(src, label):
    st, body = call('POST','/api/analyze',{'source':src,'filename':label})
    try: d=json.loads(body)
    except Exception: print(label, st, body[:200]); return None
    if 'summary' not in d: print(label, st, json.dumps(d)[:300]); return d
    s=d['summary']
    print(f"{label:<34} http={st} status={d.get('status')} accepted={d.get('accepted')} findings={s['findings']} complete={s['analysis_complete']} partial={s['partial_reasons'][:2]} errors={s['errors']} unsupported={s['unsupported_constructs']} diags={[x['code'] for x in d['diagnostics']][:6]}")
    return d
print("empty source:", call('POST','/api/analyze',{'source':'   '}))
print("missing field:", call('POST','/api/analyze',{'filename':'x'}))
print("invalid JSON:", call('POST','/api/analyze',raw=b'{not json'))
print("unknown run:", call('GET','/api/runs/doesnotexist/findings'))
print("unknown endpoint:", call('GET','/api/nope'))
print("bad parser mode:", call('POST','/api/analyze',{'source':'int main(){return 0;}','parser_mode':'earley'}))
for f in ['syntax_errors/missing_semicolon.ctc','syntax_errors/broken_expression.ctc','syntax_errors/unbalanced_braces.ctc','unsupported/switch_statement.ctc','unsupported/pointer_type.ctc','unsupported/preprocessor_directive.ctc']:
    summ(open('examples/'+f).read(), f)
summ('int main() {\n  string c = input();\n  system(c);\n  return 0;\n}\n','valid_vuln')
summ('int main() {\n  int a = 1;\n  a = b + 1;\n  return a;\n}\n','semantic_undeclared')
summ('int main() {\n  return 0;\n}\n','no_finding')
