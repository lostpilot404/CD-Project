# The CT-C subset

CodeTrace analyses a deliberately small C-like language called **CT-C subset
v1**. The subset is fixed: every construct outside it produces an explicit
diagnostic (``LEX100``, ``LEX101``, ``LEX102``, ``SYN100``) and the construct is
recorded as *unsupported* in the report. Nothing outside the subset is silently
treated as safe, and nothing is approximated without saying so.

The language is defined by the grammar below, which is the grammar the parser
actually runs. The listing is generated from the implementation, so it cannot
drift away from the code:

```bash
python3 -c "from codetrace.frontend.grammar_lang import grammar_documentation as d; \
            [print(p['display']) for p in d()]" > /tmp/grammar.txt
```

The same listing is available over HTTP at ``GET /api/grammar`` together with the
``NULLABLE``, ``FIRST`` and ``FOLLOW`` sets and the LR automaton statistics.

## 0. The grammar as implemented

All 102 productions of CT-C subset v1, indexed exactly as the parser numbers
them (``augmented start`` is production 0). ``ε`` marks an empty right-hand
side.

| # | Production | Meaning |
| --- | --- | --- |
| 0 | `program' -> program` | augmented start |
| 1 | `program -> decl_list` | translation unit |
| 2 | `decl_list -> decl_list decl` | append declaration |
| 3 | `decl_list -> ε` | empty declaration list |
| 4 | `decl -> function_decl` | function |
| 5 | `decl -> var_decl` | global variable |
| 6 | `function_decl -> type IDENT LPAREN params_opt RPAREN block` | function definition |
| 7 | `params_opt -> ε` | no parameters |
| 8 | `params_opt -> KW_VOID` | explicit void parameter list |
| 9 | `params_opt -> param_list` | parameter list |
| 10 | `param_list -> param` | one parameter |
| 11 | `param_list -> param_list COMMA param` | another parameter |
| 12 | `param -> type IDENT` | parameter |
| 13 | `type -> KW_INT` | type int |
| 14 | `type -> KW_FLOAT` | type float |
| 15 | `type -> KW_CHAR` | type char |
| 16 | `type -> KW_BOOL` | type bool |
| 17 | `type -> KW_STRING` | type string |
| 18 | `type -> KW_VOID` | type void |
| 19 | `var_decl -> type declarator_list SEMI` | declaration |
| 20 | `declarator_list -> declarator` | one declarator |
| 21 | `declarator_list -> declarator_list COMMA declarator` | another declarator |
| 22 | `declarator -> IDENT` | plain declarator |
| 23 | `declarator -> IDENT ASSIGN expr` | initialised declarator |
| 24 | `declarator -> IDENT LBRACKET INT_LIT RBRACKET` | array declarator |
| 25 | `block -> LBRACE stmt_list RBRACE` | block |
| 26 | `stmt_list -> stmt_list statement` | statement sequence |
| 27 | `stmt_list -> ε` | empty block |
| 28 | `statement -> matched_statement` | matched statement |
| 29 | `statement -> open_statement` | open statement |
| 30 | `matched_statement -> block` | matched block |
| 31 | `matched_statement -> var_decl` | matched declaration |
| 32 | `matched_statement -> expr_statement` | matched expression statement |
| 33 | `matched_statement -> empty_statement` | matched empty statement |
| 34 | `matched_statement -> jump_statement` | matched jump |
| 35 | `matched_statement -> KW_IF LPAREN expr RPAREN matched_statement KW_ELSE matched_statement` | if/else (matched) |
| 36 | `matched_statement -> KW_WHILE LPAREN expr RPAREN matched_statement` | while (matched) |
| 37 | `matched_statement -> KW_FOR LPAREN for_setup for_tail RPAREN matched_statement` | for (matched) |
| 38 | `open_statement -> KW_IF LPAREN expr RPAREN statement` | if without else (open) |
| 39 | `open_statement -> KW_IF LPAREN expr RPAREN matched_statement KW_ELSE open_statement` | if/else with open else |
| 40 | `open_statement -> KW_WHILE LPAREN expr RPAREN open_statement` | while (open) |
| 41 | `open_statement -> KW_FOR LPAREN for_setup for_tail RPAREN open_statement` | for (open) |
| 42 | `expr_statement -> expr SEMI` | expression statement |
| 43 | `empty_statement -> SEMI` | empty statement |
| 44 | `jump_statement -> KW_RETURN SEMI` | return |
| 45 | `jump_statement -> KW_RETURN expr SEMI` | return expression |
| 46 | `jump_statement -> KW_BREAK SEMI` | break |
| 47 | `jump_statement -> KW_CONTINUE SEMI` | continue |
| 48 | `for_setup -> var_decl` | for initialisation declaration |
| 49 | `for_setup -> expr_opt SEMI` | for initialisation expression |
| 50 | `for_tail -> expr_opt SEMI expr_opt` | for condition/update |
| 51 | `expr_opt -> ε` | absent expression |
| 52 | `expr_opt -> expr` | optional expression |
| 53 | `expr -> assign` | expression |
| 54 | `assign -> logic_or` | plain expression |
| 55 | `assign -> unary ASSIGN assign` | assignment = |
| 56 | `assign -> unary PLUSEQ assign` | assignment += |
| 57 | `assign -> unary MINUSEQ assign` | assignment -= |
| 58 | `assign -> unary STAREQ assign` | assignment *= |
| 59 | `assign -> unary SLASHEQ assign` | assignment /= |
| 60 | `assign -> unary PERCENTEQ assign` | assignment %= |
| 61 | `logic_or -> logic_and` | or operand |
| 62 | `logic_or -> logic_or OROR logic_and` | logical or |
| 63 | `logic_and -> equality` | and operand |
| 64 | `logic_and -> logic_and ANDAND equality` | logical and |
| 65 | `equality -> relational` | equality operand |
| 66 | `equality -> equality EQ relational` | equality |
| 67 | `equality -> equality NE relational` | inequality |
| 68 | `relational -> additive` | relational operand |
| 69 | `relational -> relational LT additive` | comparison < |
| 70 | `relational -> relational LE additive` | comparison <= |
| 71 | `relational -> relational GT additive` | comparison > |
| 72 | `relational -> relational GE additive` | comparison >= |
| 73 | `additive -> multiplicative` | additive operand |
| 74 | `additive -> additive PLUS multiplicative` | addition |
| 75 | `additive -> additive MINUS multiplicative` | subtraction |
| 76 | `multiplicative -> unary` | multiplicative operand |
| 77 | `multiplicative -> multiplicative STAR unary` | multiplication * |
| 78 | `multiplicative -> multiplicative SLASH unary` | multiplication / |
| 79 | `multiplicative -> multiplicative PERCENT unary` | multiplication % |
| 80 | `unary -> postfix` | unary operand |
| 81 | `unary -> MINUS unary` | arithmetic negation |
| 82 | `unary -> NOT unary` | logical negation |
| 83 | `unary -> INCR unary` | pre-increment |
| 84 | `unary -> DECR unary` | pre-decrement |
| 85 | `postfix -> primary` | primary expression |
| 86 | `postfix -> postfix INCR` | post-increment |
| 87 | `postfix -> postfix DECR` | post-decrement |
| 88 | `postfix -> postfix LBRACKET expr RBRACKET` | array element |
| 89 | `postfix -> postfix LPAREN args_opt RPAREN` | call |
| 90 | `args_opt -> ε` | no arguments |
| 91 | `args_opt -> arg_list` | arguments |
| 92 | `arg_list -> expr` | one argument |
| 93 | `arg_list -> arg_list COMMA expr` | another argument |
| 94 | `primary -> IDENT` | identifier |
| 95 | `primary -> INT_LIT` | integer literal |
| 96 | `primary -> FLOAT_LIT` | float literal |
| 97 | `primary -> CHAR_LIT` | character literal |
| 98 | `primary -> STRING_LIT` | string literal |
| 99 | `primary -> KW_TRUE` | true |
| 100 | `primary -> KW_FALSE` | false |
| 101 | `primary -> LPAREN expr RPAREN` | parenthesised expression |

## 1. Lexical structure

| Element | Accepted form |
| --- | --- |
| Comments | ``// line`` and ``/* block */`` (block comments may span lines) |
| Identifiers | ``[A-Za-z_][A-Za-z0-9_]*`` |
| Integer literals | decimal ``123``, hexadecimal ``0x1F``, digit separators ``1_000`` |
| Floating literals | ``1.5``, ``1.5e2``, ``1e-3`` — a digit is required on **both** sides of the dot, so ``1.`` and ``.5`` are two tokens |
| Character literals | ``'a'``, ``'\n'``, ``'\x41'`` (exactly one character; ``'ab'`` is ``LEX007``) |
| String literals | ``"text"`` with the escapes ``\n \t \r \0 \\ \" \'`` and ``\xHH`` |
| Boolean literals | ``true``, ``false`` |
| Punctuation | ``( ) { } [ ] ; , .`` |
| Operators | ``+ - * / % = == != < <= > >= && || ! ++ -- += -= *= /= %=`` |

Diagnostics raised by the lexer (see ``codetrace/frontend/lexer.py``):

| Code | Meaning |
| --- | --- |
| ``LEX001`` | unterminated string or character literal |
| ``LEX002`` | unterminated block comment |
| ``LEX003`` | malformed hexadecimal literal |
| ``LEX004`` | malformed numeric literal |
| ``LEX005`` | unknown escape sequence |
| ``LEX006`` | malformed hex escape |
| ``LEX007`` | multi-character character literal |
| ``LEX008`` | character outside the CT-C alphabet |
| ``LEX100`` | keyword that is explicitly outside the subset (see §4) |
| ``LEX101`` | preprocessor directive |
| ``LEX102`` | operator outside the subset (for example ``->``, ``&``, ``|``, ``::``) |

A lexer diagnostic never stops the scan: the lexer resumes at the next
character it can classify, so a single bad escape does not hide later errors.

## 2. Types

| Type | Notes |
| --- | --- |
| ``int`` | 64-bit-like integer semantics; integer division truncates |
| ``float`` | floating point |
| ``char`` | single character |
| ``bool`` | ``true`` / ``false``; conditions are expected to be boolean |
| ``string`` | immutable text value; not an array of characters |
| ``void`` | **return type only** — ``void x;`` is ``SEM006``, ``void`` parameters are ``SEM007`` |

Fixed-size arrays are supported: ``int values[10];``. Array elements are not
tracked individually by the data-flow and taint analyses; taint assigned to one
element is attributed to the whole array (see ``docs/LIMITATIONS.md``).

Declarations may initialise: ``string name = input();``. Multiple declarators in
one declaration (``int a, b;``) are supported.

## 3. Statements and expressions

Supported statements: declaration, assignment, expression statement, ``if`` /
``else`` (with ``else if`` chains), ``while``, ``for``, ``return``, ``break``,
``continue``, block ``{ … }`` and the empty statement ``;``.

Supported expressions: identifiers, literals, arithmetic ``+ - * / %``,
comparison ``== != < <= > >=``, logical ``&& || !``, parentheses, assignment
``= += -= *= /= %=``, increment/decrement (prefix and postfix), array indexing
``a[i]`` and function calls ``f(a, b)``.

Operator precedence and associativity are encoded directly in the grammar
(``docs/COMPILER_THEORY.md`` §2 shows the layers and how they are tested):

```
assignment     right-associative
||             left
&&             left
== !=          left
< <= > >=      left
+ -            left
* / %          left
unary  ! - +   right (prefix)
postfix ++ -- [] ()  left
```

## 4. What is explicitly *not* supported

Anything listed here is reported as an unsupported construct with its exact
location, is counted in ``summary.unsupported_constructs``, and appears in the
``unsupported`` section of the JSON report. The analysis of the surrounding
supported code still runs, but the report states that it is partial.

| Construct | Reported as |
| --- | --- |
| Preprocessor directives (``#include``, ``#define``, …) | ``LEX101`` |
| Pointers, address-of, dereference, arrow (``*p``, ``&x``, ``p->f``) | ``LEX102`` / ``SYN001`` |
| ``struct``, ``union``, ``enum``, ``typedef``, ``class``, ``namespace``, templates | ``LEX100`` |
| ``switch`` / ``case`` / ``default``, ``goto``, ``do`` / ``while`` | ``LEX100`` |
| ``static``, ``extern``, ``const``, ``volatile``, ``register``, ``auto``, ``inline`` | ``LEX100`` |
| ``signed`` / ``unsigned`` / ``long`` / ``short`` / ``double`` | ``LEX100`` |
| ``sizeof``, C++ ``new`` / ``delete``, exceptions (``try`` / ``catch`` / ``throw``) | ``LEX100`` |
| Dynamic memory, function pointers, indirect calls | ``SEM017`` / ``LEX102`` |
| Multiple translation units, linking, real ``#include`` semantics | not modelled (single file only) |

The complete keyword table with the reason for each exclusion is available at
``GET /api/language`` under ``unsupported`` and is emitted by
``codetrace/frontend/tokens.py`` (``UNSUPPORTED_KEYWORDS``).

## 5. Built-in external functions

Externals are *not* part of the language: they are named by the rule set. The
built-in rule set (``codetrace/rules/builtin/standard.ctrule``) declares the
following functions, which is why they resolve without a declaration in the
analysed file:

| External | Kind | Function | Rule id |
| --- | --- | --- | --- |
| ``input()`` | source | ``input`` | ``stdin`` |
| ``input_int()`` | source | ``input_int`` | ``stdin_int`` |
| ``readenv(name)`` | source | ``readenv`` | ``environment`` |
| ``argv(index)`` | source | ``argv`` | ``command_line`` |
| ``readfile(path)`` | source **and** path sink | ``readfile`` | ``file_content`` / ``path_readfile`` |
| ``system(c)``, ``exec(c)``, ``popen(c)`` | sink (context ``command``) | ``system`` / ``exec`` / ``popen`` | ``command_system`` / ``command_exec`` / ``command_popen`` |
| ``fopen(path)``, ``writefile(path, data)`` | sink (context ``path``) | ``fopen`` / ``writefile`` | ``path_fopen`` / ``path_writefile`` |
| ``sql_exec(text)`` | sink (context ``sql``) | ``sql_exec`` | ``sql_exec`` |
| ``printf(text)`` | sink (context ``format``) | ``printf`` | ``format_printf`` |
| ``shell_escape(v)``, ``sql_escape(v)``, ``html_escape(v)``, ``path_normalize(v)`` | sanitizer | same name | ``shell_escape``, ``sql_escape``, ``html_escape``, ``path_normalize`` |
| ``to_int(v)`` | sanitizer for every context | ``to_int`` | ``parse_to_int`` |
| ``is_safe_command(v)``, ``is_valid_path(v)`` | validator (guard) | same name | ``validate_command`` / ``validate_path`` |

Running the analysis with a custom rule set replaces or extends these names; a
function that no rule mentions is treated as *unknown*: it is never assumed to
sanitise its arguments (see ``docs/RULE_LANGUAGE.md``).

## 6. Diagnostics summary

Every diagnostic carries ``code``, ``severity`` (``error`` / ``warning`` /
``info``), ``message``, ``line``, ``col``, ``offset``, ``end_offset`` and
``phase`` (``lexer`` / ``parser`` / ``semantics`` / ``cfg`` / ``dataflow`` /
``rules``). The full catalogue is served by ``GET /api/language`` under
``diagnostics`` and includes the parser, semantics, CFG and data-flow codes:

* ``SYN001`` syntax error with the list of expected tokens, ``SYN010`` parse step
  limit, ``SYN011`` too many syntax errors, ``SYN100`` unsupported keyword
  during parsing;
* ``SEM001`` undeclared identifier, ``SEM002`` duplicate declaration, ``SEM003``
  function redefinition, ``SEM004`` assignment to a non-assignable expression,
  ``SEM005`` type error, ``SEM008`` unknown external call, ``SEM009`` wrong
  argument count, ``SEM010`` argument type mismatch, ``SEM012`` ``break`` /
  ``continue`` outside a loop, ``SEM013`` indexing a non-array, ``SEM014``
  function used as a value, ``SEM015`` duplicate parameter, ``SEM016`` return
  value mismatch, ``SEM017`` indirect call, ``SEM018`` shadowing, ``SEM020`` no
  ``main`` function, ``SEM101`` narrowing conversion, ``SEM102`` non-boolean
  condition;
* ``CFG001`` unreachable code, ``DFA001`` variable may be used before assignment.

## 7. Test pointers

| Behaviour | Test |
| --- | --- |
| Tokenisation, offsets, comments, literals | ``tests/test_lexer.py`` |
| Precedence, associativity, nesting, recovery, diagnostics | ``tests/test_parser.py`` |
| Scopes, shadowing, symbol identity, type checks | ``tests/test_semantics.py`` |
| Unsupported constructs from this document | ``tests/test_lexer.py``, ``examples/unsupported/`` |
| Running every bundled example through the real pipeline | ``evaluation/run_evaluation.py`` |
