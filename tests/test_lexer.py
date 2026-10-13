"""Lexer tests: tokens, positions, literals, comments and every lexer diagnostic."""

from __future__ import annotations

import unittest

from tests.helpers import codes, messages, parse, tokenize  # noqa: E402


class TokenTests(unittest.TestCase):
    def test_token_kinds_and_positions(self):
        result = tokenize("int x = 42;\nstring s = \"hi\";\n")
        kinds = [token.kind for token in result.tokens if token.kind != "EOF"]
        self.assertEqual(
            kinds,
            ["KW_INT", "IDENT", "ASSIGN", "INT_LIT", "SEMI", "KW_STRING", "IDENT", "ASSIGN",
             "STRING_LIT", "SEMI"],
        )
        first = result.tokens[0]
        self.assertEqual((first.line, first.col, first.offset), (1, 1, 0))
        semi = result.tokens[4]
        self.assertEqual((semi.line, semi.col, semi.offset), (1, 11, 10))
        string_lit = next(token for token in result.tokens if token.kind == "STRING_LIT")
        self.assertEqual((string_lit.line, string_lit.col), (2, 12))

    def test_offsets_reconstruct_the_original_text(self):
        source = "int  total = 1 + 2 ;\n"
        result = tokenize(source)
        for token in result.tokens:
            if token.kind == "EOF":
                continue
            self.assertEqual(source[token.offset:token.end_offset], token.text)
            self.assertEqual(len(token.text), token.end_offset - token.offset)

    def test_keywords_are_not_identifiers(self):
        result = tokenize("int intx = 1;")
        self.assertEqual([t.kind for t in result.tokens[:2]], ["KW_INT", "IDENT"])
        self.assertEqual(result.tokens[1].text, "intx")

    def test_numeric_literals(self):
        result = tokenize("int a = 0; int b = 0x1F; float c = 3.5;")
        literals = [(t.kind, t.text) for t in result.tokens if t.kind in ("INT_LIT", "FLOAT_LIT")]
        self.assertEqual(literals, [("INT_LIT", "0"), ("INT_LIT", "0x1F"), ("FLOAT_LIT", "3.5")])

    def test_string_and_char_literals_with_escapes(self):
        result = tokenize('string s = "a\\"b\\n"; char c = \'x\';')
        literals = [(t.kind, t.text) for t in result.tokens if t.kind in ("STRING_LIT", "CHAR_LIT")]
        self.assertEqual(literals, [("STRING_LIT", '"a\\"b\\n"'), ("CHAR_LIT", "'x'")])
        self.assertEqual(codes(result.diagnostics), [])

    def test_line_comments_and_block_comments(self):
        source = "// leading\nint x = 1; // trailing\n/* block\n   comment */\nint y = 2;\n"
        result = tokenize(source)
        self.assertEqual(codes(result.diagnostics), [])
        self.assertEqual(result.diagnostics, [])
        self.assertEqual(result.tokens[-2].line, 5)

    def test_block_comments_do_not_hide_real_diagnostics(self):
        source = "/* comment */ int x = @;"
        result = tokenize(source)
        self.assertIn("LEX008", codes(result.diagnostics))


class LexerDiagnosticTests(unittest.TestCase):
    def assertDiagnostic(self, source, code):
        result = tokenize(source)
        self.assertIn(code, codes(result.diagnostics), messages(result.diagnostics))
        return next(d for d in result.diagnostics if d.code == code)

    def test_unterminated_string(self):
        diagnostic = self.assertDiagnostic('string s = "abc;\n', "LEX001")
        self.assertEqual((diagnostic.line, diagnostic.col), (1, 12))
        self.assertTrue(diagnostic.detail)

    def test_unterminated_block_comment(self):
        diagnostic = self.assertDiagnostic("/* never closed\nint x = 1;\n", "LEX002")
        self.assertEqual(diagnostic.line, 1)

    def test_invalid_character(self):
        diagnostic = self.assertDiagnostic("int a = 1; int b = 2 @ 3;", "LEX008")
        self.assertEqual(diagnostic.col, 22)
        self.assertIn("@", diagnostic.message)

    def test_malformed_hex_literal(self):
        self.assertDiagnostic("int a = 0xZZ;", "LEX003")

    def test_malformed_number(self):
        diagnostic = self.assertDiagnostic("int a = 12abc;", "LEX004")
        self.assertEqual(diagnostic.line, 1)

    def test_unknown_escape_sequence(self):
        self.assertDiagnostic('string s = "a\\qb";', "LEX005")

    def test_multichar_character_literal(self):
        self.assertDiagnostic("char c = 'ab';", "LEX007")

    def test_preprocessor_directive_is_reported_not_ignored(self):
        diagnostic = self.assertDiagnostic('#include "x.h"\nint main() { return 0; }\n', "LEX101")
        self.assertTrue(diagnostic.unsupported)
        self.assertIn("preprocessor", diagnostic.message.lower())

    def test_unsupported_keyword_is_reported(self):
        diagnostic = self.assertDiagnostic("int main() { switch (1) { } return 0; }", "LEX100")
        self.assertEqual(diagnostic.line, 1)
        self.assertIn("switch", messages([diagnostic]))

    def test_unsupported_operator_is_reported(self):
        self.assertDiagnostic("int main() { int x = 1; x << 2; return x; }", "LEX102")


class LexerWithParserTests(unittest.TestCase):
    def test_lexer_errors_are_handed_to_the_parser_run(self):
        outcome = parse("int main() { string s = \"open; return 0; }\n")
        self.assertIn("LEX001", codes(outcome.diagnostics))
        self.assertFalse(outcome.accepted)

    def test_clean_file_has_no_diagnostics(self):
        outcome = parse("int main() { int a = 1; return a; }\n")
        self.assertEqual(codes(outcome.diagnostics), [])
        self.assertTrue(outcome.accepted)


if __name__ == "__main__":
    unittest.main()
