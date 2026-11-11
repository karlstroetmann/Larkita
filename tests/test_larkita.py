import os
import re
import shutil
import tempfile
import unittest
import warnings

from larkita import (Larkita, GrammarError, ConflictWarning, UnexpectedToken, UnexpectedCharacters)
from larkita.load_grammar import GRAMMAR_ERRORS
from larkita.lr_analysis import LR1Analyzer

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'new-syntax')

LEXICAL = '''
%import common.CNAME -> IDENTIFIER
%import common.INT -> NUMBER
%import common.WS
%ignore WS
'''


class LarkitaTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def make(self, grammar, **options):
        options.setdefault('out_file', os.path.join(self.tmpdir, 'grammar.out'))
        return Larkita(grammar + LEXICAL, **options)

    def parse(self, grammar, text, **options):
        return self.make(grammar, **options).parse(text)


class TestSpecificationExamples(LarkitaTestCase):
    "The examples (a) - (i) of the specification in Claude.md"

    def test_a(self):
        g = 'stmnt: IDENTIFIER ":=" expr ";"\nexpr: NUMBER'
        self.assertEqual(self.parse(g, 'x := 1;'), ((':=', ';'), ('IDENTIFIER', 'x'), ('NUMBER', '1')))

    def test_b(self):
        g = 'stmnt: expr ";"\nexpr: NUMBER'
        self.assertEqual(self.parse(g, '1;'), (';', ('NUMBER', '1')))

    def test_c(self):
        g = 'expr: expr "+" product | product\nproduct: NUMBER'
        self.assertEqual(self.parse(g, '1 + 2 + 3'),
                         ('+', ('+', ('NUMBER', '1'), ('NUMBER', '2')), ('NUMBER', '3')))

    def test_d(self):
        g = '''
        expr: expr "+" factor | factor
        factor: "(" expr ")"    %ignore "(", ")"
              | NUMBER
        '''
        self.assertEqual(self.parse(g, '((1))'), ('NUMBER', '1'))
        self.assertEqual(self.parse(g, '(1 + 2)'), ('+', ('NUMBER', '1'), ('NUMBER', '2')))

    def test_e(self):
        g = 'a: "if" expr "then" expr "else" expr\nexpr: NUMBER'
        self.assertEqual(self.parse(g, 'if 1 then 2 else 3'),
                         (('if', 'then', 'else'), ('NUMBER', '1'), ('NUMBER', '2'), ('NUMBER', '3')))

    def test_f(self):
        g = '''
        atom: IDENTIFIER "(" expr_list ")" -> "call"
            | NUMBER
        expr_list: (atom ("," atom)*)
        '''
        self.assertEqual(self.parse(g, 'f(1, 2)'),
                         ('call', ('IDENTIFIER', 'f'), (',', ('NUMBER', '1'), ('NUMBER', '2'))))

    def test_g(self):
        g = 'atom: IDENTIFIER'
        self.assertEqual(self.parse(g, 'abc'), ('IDENTIFIER', 'abc'))

    def test_h(self):
        g = 'expr_list: (expr ("," expr)*)\nexpr: NUMBER'
        self.assertEqual(self.parse(g, '1, 2, 3'), (',', ('NUMBER', '1'), ('NUMBER', '2'), ('NUMBER', '3')))
        # The head is determined statically, so it is there even if there is only one expression
        self.assertEqual(self.parse(g, '1'), (',', ('NUMBER', '1')))

    def test_i(self):
        g = 'set_expr: "{" expr ("," expr)* "}"\nexpr: NUMBER'
        self.assertEqual(self.parse(g, '{1, 2}'), (('{', ',', '}'), ('NUMBER', '1'), ('NUMBER', '2')))
        self.assertEqual(self.parse(g, '{1}'), (('{', ',', '}'), ('NUMBER', '1')))


class TestClarifications(LarkitaTestCase):
    "The clarifications 1 - 12 in Claude.md"

    def test_head_has_one_entry_per_occurrence(self):
        g = 'a: "for" "(" b ";" b ";" b ")"\nb: NUMBER'
        self.assertEqual(self.parse(g, 'for (1; 2; 3)'),
                         (('for', '(', ';', ';', ')'), ('NUMBER', '1'), ('NUMBER', '2'), ('NUMBER', '3')))

    def test_passthrough_is_static(self):
        g = 'program: statement*\nstatement: NUMBER ";"'
        self.assertEqual(self.parse(g, '1;'), ('program', (';', ('NUMBER', '1'))))
        self.assertEqual(self.parse(g, '1; 2;'), ('program', (';', ('NUMBER', '1')), (';', ('NUMBER', '2'))))

    def test_passthrough_of_group_with_one_symbol(self):
        g = 'a: (b)\nb: NUMBER'
        self.assertEqual(self.parse(g, '1'), ('NUMBER', '1'))

    def test_rule_name_as_head(self):
        g = 'program: statement*\nstatement: NUMBER'
        self.assertEqual(self.parse(g, ''), ('program',))
        g = 'pair: atom atom\natom: NUMBER'
        self.assertEqual(self.parse(g, '1 2'), ('pair', ('NUMBER', '1'), ('NUMBER', '2')))
        g = 'set: "{" "}"  %ignore "{", "}"'
        self.assertEqual(self.parse(g, '{}'), ('set',))

    def test_flattening(self):
        g = 'a: b ("," b ("+" b)*)*\nb: NUMBER'
        self.assertEqual(self.parse(g, '1, 2 + 3, 4'),
                         ((',', '+'), ('NUMBER', '1'), ('NUMBER', '2'), ('NUMBER', '3'), ('NUMBER', '4')))

    def test_plus(self):
        g = 'a: "[" b+ "]"\nb: NUMBER'
        self.assertEqual(self.parse(g, '[1 2 3]'), (('[', ']'), ('NUMBER', '1'), ('NUMBER', '2'), ('NUMBER', '3')))

    def test_optional_is_omitted(self):
        g = 'stmt: "return" [expr] ";"\nexpr: NUMBER'
        self.assertEqual(self.parse(g, 'return;'), (('return', ';'),))
        self.assertEqual(self.parse(g, 'return 1;'), (('return', ';'), ('NUMBER', '1')))
        g = 'stmt: "return" expr? ";"\nexpr: NUMBER'
        self.assertEqual(self.parse(g, 'return;'), (('return', ';'),))

    def test_literals_in_optional_part_belong_to_the_head(self):
        g = 'stmt: "if" expr "then" expr ["else" expr]\nexpr: NUMBER'
        head = ('if', 'then', 'else')
        self.assertEqual(self.parse(g, 'if 1 then 2'), (head, ('NUMBER', '1'), ('NUMBER', '2')))

    def test_inner_alternatives_are_expanded(self):
        g = 'a: b ("+" | "-") b\nb: NUMBER'
        self.assertEqual(self.parse(g, '1 - 2'), ('-', ('NUMBER', '1'), ('NUMBER', '2')))
        g = 'a: "if" b ("then" | ":") b\nb: NUMBER'
        self.assertEqual(self.parse(g, 'if 1 : 2'), (('if', ':'), ('NUMBER', '1'), ('NUMBER', '2')))
        g = 'a: (b | "-" b)\nb: NUMBER'
        self.assertEqual(self.parse(g, '1'), ('NUMBER', '1'))
        self.assertEqual(self.parse(g, '-1'), ('-', ('NUMBER', '1')))

    def test_literals_of_inner_alternatives_in_repetitions_are_children(self):
        g = 'expr: product (("+" | "-") product)*\nproduct: NUMBER'
        self.assertEqual(self.parse(g, '1 - 2 + 3'),
                         ('expr', ('NUMBER', '1'), '-', ('NUMBER', '2'), '+', ('NUMBER', '3')))
        g = 'a: b [("+" | "-") b]\nb: NUMBER'
        self.assertEqual(self.parse(g, '1 + 2'), ('a', ('NUMBER', '1'), '+', ('NUMBER', '2')))
        self.assertEqual(self.parse(g, '1'), ('a', ('NUMBER', '1')))
        g = 'a: b (("and"i | "or"i) b)*\nb: NUMBER'
        self.assertEqual(self.parse(g, '1 AND 2'), ('a', ('NUMBER', '1'), 'and', ('NUMBER', '2')))

    def test_literals_of_inner_alternatives_with_alias_are_children(self):
        g = 'a: b ("+" | "-") b -> binop\nb: NUMBER'
        self.assertEqual(self.parse(g, '1 - 2'), ('binop', ('NUMBER', '1'), '-', ('NUMBER', '2')))

    def test_ignored_literals_of_inner_alternatives(self):
        g = 'a: b (("+" | "-") b)*  %ignore "+"\nb: NUMBER'
        self.assertEqual(self.parse(g, '1 + 2 - 3'), ('a', ('NUMBER', '1'), ('NUMBER', '2'), '-', ('NUMBER', '3')))

    def test_same_repetition_with_literal_in_head_and_as_child(self):
        # The rules x and y must not share the auxiliary rule for ("," b)*
        g = 'a: x | y\nx: b ("," b)*\ny: "!" b [("," b)* | ";"]\nb: NUMBER'
        self.assertEqual(self.parse(g, '1, 2'), (',', ('NUMBER', '1'), ('NUMBER', '2')))
        self.assertEqual(self.parse(g, '! 1, 2'), ('!', ('NUMBER', '1'), ',', ('NUMBER', '2')))

    def test_named_tokens_and_regexps(self):
        g = 'a: NUMBER /[a-z]+/'
        tree = self.parse(g, '1 abc')
        self.assertEqual(tree[0], 'a')
        self.assertEqual(tree[1], ('NUMBER', '1'))
        self.assertEqual(tree[2][1], 'abc')

    def test_aliases(self):
        g = '''
        factor: "-" factor -> neg
              | "+" factor -> "pos"
              | IDENTIFIER -> var
              | NUMBER
        '''
        self.assertEqual(self.parse(g, '-+x'), ('neg', ('pos', ('var', ('IDENTIFIER', 'x')))))

    def test_ignore_applies_to_its_alternative_only(self):
        g = '''
        a: "(" b ")"    %ignore "(", ")"
         | "[" b "]"
        b: NUMBER
        '''
        self.assertEqual(self.parse(g, '(1)'), ('NUMBER', '1'))
        self.assertEqual(self.parse(g, '[1]'), (('[', ']'), ('NUMBER', '1')))

    def test_ignore_some_literals(self):
        g = 'a: "if" "(" b ")" b    %ignore "(", ")"\nb: NUMBER'
        self.assertEqual(self.parse(g, 'if (1) 2'), ('if', ('NUMBER', '1'), ('NUMBER', '2')))

    def test_global_ignore(self):
        g = '''
        stmt: "while" "(" expr ")" stmt
            | "{" stmt* "}"
            | expr ";"
        expr: "(" expr ")" | NUMBER
        %ignore: "(", ")", "{", "}"
        '''
        self.assertEqual(self.parse(g, 'while ((1)) { 2; }'),
                         ('while', ('NUMBER', '1'), ('stmt', (';', ('NUMBER', '2')))))

    def test_list_of_ignored_terminals(self):
        g = 'a: NUMBER*\nCOMMENT: /#[^\\n]*/\nSEMI: ";"\n'
        one_per_line = self.make(g + '%ignore COMMENT\n%ignore SEMI\n')
        as_list = self.make(g + '%ignore COMMENT, SEMI\n')
        self.assertEqual(as_list.grammar.ignore, one_per_line.grammar.ignore)
        self.assertEqual(as_list.parse('1; # one\n2'), ('a', ('NUMBER', '1'), ('NUMBER', '2')))

    def test_list_of_ignored_expansions(self):
        g = 'a: NUMBER*\n%ignore /#[^\\n]*/, ";"\n'
        self.assertEqual(self.parse(g, '1; # one\n2'), ('a', ('NUMBER', '1'), ('NUMBER', '2')))

    def test_list_of_imports(self):
        g = 'a: (ID | INT)*\n%ignore WS\n'
        out_file = os.path.join(self.tmpdir, 'grammar.out')
        one_per_line = Larkita(g + '%import common.CNAME -> ID\n%import common.INT\n%import common.WS\n',
                               out_file=out_file)
        as_list = Larkita(g + '%import common.CNAME -> ID, common.INT, common.WS\n', out_file=out_file)
        self.assertEqual(sorted((str(t.name), t.pattern) for t in as_list.terminals),
                         sorted((str(t.name), t.pattern) for t in one_per_line.terminals))
        self.assertEqual(as_list.parse('x 1'), ('a', ('ID', 'x'), ('INT', '1')))

    def test_list_of_imports_with_a_multi_import(self):
        g = 'a: (ID | INT)*\n%import common (INT, WS), common.CNAME -> ID\n%ignore WS\n'
        parser = Larkita(g, out_file=os.path.join(self.tmpdir, 'grammar.out'))
        self.assertEqual(parser.parse('x 1'), ('a', ('ID', 'x'), ('INT', '1')))

    def test_start_symbol(self):
        g = 'a: b ";"\nb: NUMBER'
        self.assertEqual(self.make(g).start, 'a')
        self.assertEqual(self.parse(g, '1', start='b'), ('NUMBER', '1'))

    def test_first_rule_after_imports_and_terminals(self):
        g = '%import common.LETTER\nA: "a"\nfirst: LETTER\nsecond: first'
        self.assertEqual(self.make(g).start, 'first')

    def test_basic_lexer(self):
        g = 'expr: expr "+" NUMBER | NUMBER'
        self.assertEqual(self.parse(g, '1 + 2', lexer='basic'), ('+', ('NUMBER', '1'), ('NUMBER', '2')))

    def test_lex(self):
        g = 'stmt: "if" NUMBER "then" IDENTIFIER'
        tokens = list(self.make(g).lex('if 1\nthen x'))
        self.assertEqual([(t.type, t.value) for t in tokens],
                         [('IF', 'if'), ('NUMBER', '1'), ('THEN', 'then'), ('IDENTIFIER', 'x')])
        self.assertEqual((tokens[2].line, tokens[2].column), (2, 1))

    def test_long_lists(self):
        g = 'a: b ("," b)*\nb: NUMBER'
        tree = self.parse(g, ', '.join(['1'] * 20000))
        self.assertEqual(len(tree), 20001)


class TestLR1(LarkitaTestCase):

    def test_lr1_but_not_lalr1(self):
        # Merging the states that are reached by "a" "e" and "b" "e" (as LALR does)
        # results in a reduce/reduce conflict.
        g = '''
        s: "a" e "c" | "a" f "d" | "b" f "c" | "b" e "d"
        e: "x" -> e
        f: "x" -> f
        '''
        parser = self.make(g)
        self.assertEqual(parser.conflicts, [])
        self.assertEqual(parser.parse('axc'), (('a', 'c'), ('e',)))
        self.assertEqual(parser.parse('axd'), (('a', 'd'), ('f',)))
        self.assertEqual(parser.parse('bxc'), (('b', 'c'), ('f',)))
        self.assertEqual(parser.parse('bxd'), (('b', 'd'), ('e',)))

    def test_shift_reduce_conflict_is_resolved_as_shift(self):
        g = '''
        stmt: "if" expr "then" stmt
            | "if" expr "then" stmt "else" stmt
            | expr
        expr: NUMBER
        '''
        with self.assertWarns(ConflictWarning):
            parser = self.make(g)
        self.assertEqual([c.kind for c in parser.conflicts], ['shift/reduce'])
        # The "else" belongs to the inner "if"
        self.assertEqual(parser.parse('if 1 then if 2 then 3 else 4'),
                         (('if', 'then'), ('NUMBER', '1'),
                          (('if', 'then', 'else'), ('NUMBER', '2'), ('NUMBER', '3'), ('NUMBER', '4'))))

    def test_conflict_warning_refers_to_the_caller(self):
        g = 'stmt: "if" NUMBER "then" stmt | "if" NUMBER "then" stmt "else" stmt | NUMBER' + LEXICAL
        path = os.path.join(self.tmpdir, 'dangling.lark')
        with open(path, 'w') as handle:
            handle.write(g)
        out_file = os.path.join(self.tmpdir, 'grammar.out')
        for create in [lambda: Larkita(g, out_file=out_file), lambda: Larkita.open(path, out_file=out_file)]:
            with self.assertWarns(ConflictWarning) as cm:
                create()
            self.assertEqual(cm.filename, __file__)

    def test_reduce_reduce_conflict_is_an_error(self):
        g = 'a: b | c\nb: NUMBER\nc: NUMBER'
        out_file = os.path.join(self.tmpdir, 'conflict.out')
        with self.assertRaises(GrammarError) as cm:
            self.make(g, out_file=out_file)
        self.assertIn('reduce/reduce', str(cm.exception))
        # The output file is written anyway
        with open(out_file, encoding='utf8') as f:
            self.assertIn('NOT RESOLVED', f.read())

    def test_reduce_reduce_conflict_resolved_by_priority(self):
        g = 'a: b | c\nb.2: NUMBER\nc: NUMBER'
        parser = self.make(g)
        self.assertEqual(parser.parse('1'), ('NUMBER', '1'))
        self.assertTrue(all(c.resolved for c in parser.conflicts))


def N(text):
    return ('NUMBER', text)


class TestPrecedence(LarkitaTestCase):
    "Shift/reduce conflicts are resolved by precedence declarations as in bison"

    EXPR = '''
    %nonassoc "<" "="
    %left "+" "-"
    %left "*" "/"
    %precedence UMINUS
    %right "^"

    expr: expr ("<" | "=" | "+" | "-" | "*" | "/" | "^") expr
        | "-" expr          %prec UMINUS
        | "(" expr ")"      %ignore "(", ")"
        | NUMBER
    '''

    def make_quietly(self, grammar, **options):
        "Generates the parser and checks that there is no ConflictWarning"
        with warnings.catch_warnings():
            warnings.simplefilter('error', ConflictWarning)
            return self.make(grammar, **options)

    def test_higher_precedence_wins(self):
        parser = self.make_quietly(self.EXPR)
        self.assertEqual(parser.parse('1 + 2 * 3'), ('+', N('1'), ('*', N('2'), N('3'))))
        self.assertEqual(parser.parse('1 * 2 + 3'), ('+', ('*', N('1'), N('2')), N('3')))
        self.assertEqual(parser.parse('1 + 2 < 3 * 4'), ('<', ('+', N('1'), N('2')), ('*', N('3'), N('4'))))

    def test_associativity(self):
        parser = self.make_quietly(self.EXPR)
        self.assertEqual(parser.parse('1 - 2 + 3'), ('+', ('-', N('1'), N('2')), N('3')))
        self.assertEqual(parser.parse('1 / 2 * 3'), ('*', ('/', N('1'), N('2')), N('3')))
        self.assertEqual(parser.parse('1 ^ 2 ^ 3'), ('^', N('1'), ('^', N('2'), N('3'))))

    def test_prec(self):
        parser = self.make_quietly(self.EXPR)
        self.assertEqual(parser.parse('-1 ^ 2'), ('-', ('^', N('1'), N('2'))))
        self.assertEqual(parser.parse('-1 * 2'), ('*', ('-', N('1')), N('2')))
        self.assertEqual(parser.parse('1 - -2 - 3'), ('-', ('-', N('1'), ('-', N('2'))), N('3')))

    def test_nonassoc(self):
        parser = self.make_quietly(self.EXPR)
        self.assertEqual(parser.parse('(1 < 2) = 3'), ('=', ('<', N('1'), N('2')), N('3')))
        with self.assertRaises(UnexpectedToken) as cm:
            parser.parse('1 < 2 = 3')
        self.assertEqual((cm.exception.token, cm.exception.column), ('=', 7))
        self.assertNotIn('EQUAL', cm.exception.expected)
        self.assertIn('PLUS', cm.exception.expected)

    def test_conflicts_resolved_by_precedence(self):
        parser = self.make_quietly(self.EXPR)
        self.assertTrue(parser.conflicts)
        self.assertTrue(all(c.precedence is not None for c in parser.conflicts))

    def test_rule_has_the_precedence_of_its_last_terminal(self):
        # As in bison, the rule '(+ !) expr' has no precedence, since "!" has none.
        g = '%left "+"\nexpr: expr "+" "!" expr | expr "+" expr | NUMBER'
        with self.assertWarns(ConflictWarning):
            parser = self.make(g)
        self.assertEqual({c.precedence is None for c in parser.conflicts}, {True, False})
        self.assertEqual(parser.parse('1 + 2 + 3'), ('+', ('+', N('1'), N('2')), N('3')))
        self.assertEqual(parser.parse('1 + ! 2 + 3'), (('+', '!'), N('1'), ('+', N('2'), N('3'))))

    def test_precedence_without_associativity(self):
        # %precedence cannot resolve a conflict between symbols with the same precedence
        g = '%precedence "+"\n%precedence "*"\nexpr: expr ("+" | "*") expr | NUMBER'
        with self.assertWarns(ConflictWarning):
            parser = self.make(g)
        self.assertEqual(parser.parse('1 + 2 + 3'), ('+', N('1'), ('+', N('2'), N('3'))))
        self.assertEqual(parser.parse('1 * 2 + 3'), ('+', ('*', N('1'), N('2')), N('3')))

    def test_prec_with_literal_and_alias(self):
        g = '''
        %left "+"
        %left "*"
        expr: expr ("+" | "*") expr
            | "~" expr     %prec "*"
            | "-" expr     %prec "+"  -> neg
            | NUMBER
        '''
        parser = self.make_quietly(g)
        self.assertEqual(parser.parse('~ 1 * 2'), ('*', ('~', N('1')), N('2')))
        self.assertEqual(parser.parse('- 1 * 2'), ('neg', ('*', N('1'), N('2'))))
        self.assertEqual(parser.parse('- 1 + 2'), ('+', ('neg', N('1')), N('2')))

    def test_commas_are_optional(self):
        g = '%left "+", "-" "*"\nexpr: expr ("+" | "-" | "*") expr | NUMBER'
        self.assertEqual(self.make_quietly(g).parse('1 * 2 - 3 + 4'),
                         ('+', ('-', ('*', N('1'), N('2')), N('3')), N('4')))

    def test_literals_and_named_terminals(self):
        # A literal and the terminal that is defined by it are the same symbol
        for g in ['PLUS: "+"\n%left PLUS\nexpr: expr "+" expr | NUMBER',
                  'PLUS: "+"\n%left "+"\nexpr: expr PLUS expr | NUMBER']:
            parser = self.make_quietly(g)
            self.assertEqual(parser.parse('1 + 2 + 3')[1][0], parser.parse('1 + 2')[0])

    def test_output_file(self):
        parser = self.make_quietly(self.EXPR)
        with open(parser.out_file, encoding='utf8') as f:
            report = f.read()
        n = len(parser.conflicts)
        self.assertIn('Conflicts:    %d (%d resolved by precedence, 0 unresolved)' % (n, n), report)
        self.assertIn('\n  %nonassoc    "<" "="\n  %left        "+" "-"\n', report)
        self.assertIn('\n  %precedence  UMINUS\n  %right       "^"\n', report)
        self.assertRegex(report, r'\(8\) +expr → "-" expr +UMINUS\n')
        # As in bison, the look-ahead token is on the right if the conflict is resolved as shift
        for token, reason in [('+', 'resolved as reduce (%left "+")'), ('^', 'resolved as shift (%right "^")'),
                              ('*', 'resolved as shift ("+" < "*")'), ('+', 'resolved as reduce ("+" < "*")'),
                              ('^', 'resolved as shift (UMINUS < "^")'),
                              ('<', 'resolved as an error (%nonassoc "<")')]:
            self.assertIn(', shift/reduce conflict on "%s", %s\n' % (token, reason), report)
        self.assertRegex(report, r'\n    "<" +error \(nonassociative\)\n')

    def test_no_precedence_section_without_declarations(self):
        parser = self.make('expr: expr "+" NUMBER | NUMBER')
        with open(parser.out_file, encoding='utf8') as f:
            report = f.read()
        self.assertNotIn('Precedence', report)
        self.assertIn('Conflicts:    0 (0 unresolved)', report)

    def test_errors(self):
        g = 'expr: expr "+" expr | "-" expr %prec UMINUS | NUMBER\n'
        for precedence, message in [
                ('%left "+"\n%right "+"', 'The precedence of "+" is declared twice'),
                ('%left "+" "*"\n%left UMINUS', 'The literal "*" after %left does not occur in the grammar'),
                ('%left "+" PLUSS\n%left UMINUS', 'PLUSS after %left is neither a terminal nor used after %prec'),
                ('%left "+"', 'UMINUS after %prec in rule expr has no precedence'),
                ('%left "+"\n%left UMINUS\n%left "-" NUMBER', None)]:
            with self.subTest(precedence=precedence):
                if message is None:
                    self.make_quietly(precedence + '\n' + g)
                else:
                    with self.assertRaisesRegex(GrammarError, re.escape(message)):
                        self.make(precedence + '\n' + g)
        with self.assertRaisesRegex(GrammarError, '%prec can only be given at the end of an alternative'):
            self.make('%left "+"\nexpr: (expr "+" expr %prec "+") | NUMBER')
        with self.assertRaisesRegex(GrammarError, '%prec are not allowed in terminals'):
            self.make('%left "+"\nexpr: expr "+" expr | NUMBER\nA: "a" %prec "+"')
        with self.assertRaisesRegex(GrammarError, re.escape('%prec has to be given before an alias (->) or %ignore')):
            self.make('%left "+"\nexpr: expr "+" expr | "-" expr -> neg %prec "+" | NUMBER')

    def test_imported_grammars_have_no_precedence_declarations(self):
        with open(os.path.join(self.tmpdir, 'ops.lark'), 'w') as handle:
            handle.write('%left "+"\nsum: sum "+" sum | INT\n%import common.INT\n')
        g = 'start: sum\n%import .ops.sum\n%ignore " "'
        path = os.path.join(self.tmpdir, 'start.lark')
        with open(path, 'w') as handle:
            handle.write(g)
        with self.assertWarns(ConflictWarning):
            Larkita.open(path)
        with open(path, 'w') as handle:
            handle.write('%left "+"\n' + g)
        parser = self.make_quietly(open(path).read(), source_path=path)
        self.assertEqual(parser.parse('1 + 2 + 3'),
                         ('+', ('+', ('ops__INT', '1'), ('ops__INT', '2')), ('ops__INT', '3')))


class TestMergeStates(LarkitaTestCase):
    "The option merge_states=True merges states with the same core, as long as this is safe"

    STATEMENTS = '''
    program: stmt*
    stmt: IDENTIFIER ":=" expr ";"
        | "if" "(" expr ")" stmt "else" stmt    -> "if"
        | "{" stmt* "}"                          -> block
    expr: expr "+" atom
        | atom
    atom: "(" expr ")"
        | NUMBER
        | IDENTIFIER
    %ignore: "(", ")", "{", "}", ";"
    '''

    def cores(self, parser):
        "The number of states of the LALR(1) automaton"
        states = LR1Analyzer(parser.rules, parser.start).states
        return len({frozenset(state.kernel) for state in states})

    def test_lalr_grammar_with_basic_lexer_yields_lalr_automaton(self):
        canonical = self.make(self.STATEMENTS, lexer='basic')
        merged = self.make(self.STATEMENTS, lexer='basic', merge_states=True)
        self.assertLess(len(merged.parse_table.states), len(canonical.parse_table.states))
        self.assertEqual(len(merged.parse_table.states), self.cores(canonical))
        text = 'x := 1; if (x) { y := (x + 2) + 3; } else z := y;'
        self.assertEqual(merged.parse(text), canonical.parse(text))

    def test_syntax_errors_are_found_at_the_same_token(self):
        canonical = self.make(self.STATEMENTS)
        merged = self.make(self.STATEMENTS, merge_states=True)
        for text in ['x := (1 + ;', 'if (x) y := 1; z := 2;', 'x := 1; }', 'x := 1 +']:
            errors = []
            for parser in canonical, merged:
                with self.assertRaises(UnexpectedToken) as cm:
                    parser.parse(text)
                errors.append((cm.exception.line, cm.exception.column))
            self.assertEqual(errors[0], errors[1], text)

    def test_contextual_lexer_is_respected(self):
        # After a statement, the contextual lexer of the canonical parser reads "else" as an
        # identifier.  Merging the state that follows the statement in the then-branch of an "if"
        # (which accepts "else") with the other states would make the lexer read a keyword.
        text = 'x := 1; else := 2;'
        expected = ('program', (':=', ('IDENTIFIER', 'x'), ('NUMBER', '1')),
                               (':=', ('IDENTIFIER', 'else'), ('NUMBER', '2')))
        self.assertEqual(self.parse(self.STATEMENTS, text), expected)
        merged = self.make(self.STATEMENTS, merge_states=True)
        self.assertEqual(merged.parse(text), expected)
        self.assertGreater(len(merged.parse_table.states), self.cores(merged))
        with open(merged.out_file, encoding='utf8') as f:
            self.assertIn('(collides with IDENTIFIER)', f.read())

    def test_lr1_but_not_lalr1(self):
        g = '''
        s: "a" e "c" | "a" f "d" | "b" f "c" | "b" e "d"
        e: "x" -> e
        f: "x" -> f
        '''
        parser = self.make(g, merge_states=True, lexer='basic')
        self.assertEqual(parser.conflicts, [])
        self.assertEqual(len(parser.parse_table.states), self.cores(parser) + 1)
        self.assertEqual(parser.parse('axc'), (('a', 'c'), ('e',)))
        self.assertEqual(parser.parse('axd'), (('a', 'd'), ('f',)))
        self.assertEqual(parser.parse('bxc'), (('b', 'c'), ('f',)))
        self.assertEqual(parser.parse('bxd'), (('b', 'd'), ('e',)))
        with open(parser.out_file, encoding='utf8') as f:
            report = f.read()
        self.assertIn('merging them would cause a conflict', report)
        self.assertIn('reduces using rule (5) e → "x"', report)

    def test_shift_reduce_conflicts_are_merged(self):
        g = '''
        stmt: "if" expr "then" stmt
            | "if" expr "then" stmt "else" stmt
            | expr
        expr: NUMBER
        '''
        with self.assertWarns(ConflictWarning):
            parser = self.make(g, merge_states=True)
        self.assertEqual([c.kind for c in parser.conflicts], ['shift/reduce'])
        self.assertEqual(parser.parse('if 1 then if 2 then 3 else 4'),
                         (('if', 'then'), ('NUMBER', '1'),
                          (('if', 'then', 'else'), ('NUMBER', '2'), ('NUMBER', '3'), ('NUMBER', '4'))))

    def test_precedence(self):
        canonical = self.make(TestPrecedence.EXPR)
        merged = self.make(TestPrecedence.EXPR, merge_states=True)
        self.assertLess(len(merged.parse_table.states), len(canonical.parse_table.states))
        for text in ['1 + 2 * -3 ^ 4 ^ 5 - 6', '(1 < 2) = (3 - 4 - 5)', '-(1 + 2) / 3 < 4 * 5']:
            self.assertEqual(merged.parse(text), canonical.parse(text))
        for text in ['1 < 2 = 3', '(1 + 2 < 3 < 4)', '1 + * 2', '(1 + 2']:
            errors = []
            for parser in canonical, merged:
                with self.assertRaises(UnexpectedToken) as cm:
                    parser.parse(text)
                errors.append((cm.exception.line, cm.exception.column))
            self.assertEqual(errors[0], errors[1], text)

    def test_nonassoc_errors_are_not_merged_with_shifts(self):
        # After "a" "?", the token "<" is an error because of %nonassoc, while after "b" "?" it is
        # shifted.  The states have the same core, but merging them would accept "a ? < 1 < 2".
        g = '''
        %nonassoc "?" "<"
        s: "a" x "<" NUMBER | "b" x
        x: "?" | "?" "<" NUMBER
        '''
        parser = self.make(g, merge_states=True, lexer='basic')
        self.assertEqual(parser.parse('b ? < 1'), ('b', (('?', '<'), N('1'))))
        with self.assertRaises(UnexpectedToken):
            parser.parse('a ? < 1 < 2')
        with open(parser.out_file, encoding='utf8') as f:
            self.assertRegex(f.read(), r'state \d+ rejects "<" \(%nonassoc\)')

    def test_reduce_reduce_conflict_is_still_an_error(self):
        with self.assertRaises(GrammarError):
            self.make('a: b | c\nb: NUMBER\nc: NUMBER', merge_states=True)

    def test_output_file(self):
        parser = self.make(self.STATEMENTS, lexer='basic', merge_states=True)
        with open(parser.out_file, encoding='utf8') as f:
            report = f.read()
        self.assertIn('LR(1) automaton with merged states', report)
        self.assertIn('merged from the LR(1) states', report)
        self.assertIn('so this is the\nLALR(1) automaton', report)


class TestOutputFile(LarkitaTestCase):

    def test_out_file_next_to_grammar_file(self):
        path = os.path.join(self.tmpdir, 'expr.g')
        with open(path, 'w') as f:
            f.write('expr: expr "+" NUMBER | NUMBER\n' + LEXICAL)
        parser = Larkita.open(path)
        self.assertEqual(parser.out_file, os.path.join(self.tmpdir, 'expr.out'))
        with open(parser.out_file, encoding='utf8') as f:
            report = f.read()
        self.assertIn('expr → expr "+" NUMBER', report)
        self.assertIn('expr → expr • "+" NUMBER', report)
        self.assertIn('⇒ ("+", ast(expr), ("NUMBER", text))', report)

    def test_out_file_for_string_grammar(self):
        cwd = os.getcwd()
        os.chdir(self.tmpdir)
        try:
            Larkita('a: "x"')
            self.assertTrue(os.path.exists(os.path.join(self.tmpdir, 'grammar.out')))
        finally:
            os.chdir(cwd)

    def test_lookaheads_are_listed(self):
        g = 'a: b "x" | "y" b "z"\nb: NUMBER'
        out_file = os.path.join(self.tmpdir, 'la.out')
        self.make(g, out_file=out_file)
        with open(out_file, encoding='utf8') as f:
            report = f.read()
        # Canonical LR(1) keeps the two occurrences of b apart
        self.assertIn('b → NUMBER •  { "x" }', report)
        self.assertIn('b → NUMBER •  { "z" }', report)

    def test_literals_that_are_children_are_shown(self):
        g = 'expr: NUMBER (("+" | "-") NUMBER)*'
        out_file = os.path.join(self.tmpdir, 'children.out')
        self.make(g, out_file=out_file)
        with open(out_file, encoding='utf8') as f:
            report = f.read()
        self.assertIn('__expr_star_0 → "-" NUMBER', report)
        self.assertIn('⇒ ["-", ("NUMBER", text)]', report)


class TestErrors(LarkitaTestCase):

    def test_unexpected_token(self):
        g = 'stmnt: expr ";"\nexpr: NUMBER'
        with self.assertRaises(UnexpectedToken) as cm:
            self.parse(g, '1 2')
        self.assertEqual(cm.exception.token.type, 'NUMBER')
        self.assertIn('";"', str(cm.exception))

    def test_unexpected_end_of_input(self):
        g = 'stmnt: expr ";"\nexpr: NUMBER'
        with self.assertRaises(UnexpectedToken) as cm:
            self.parse(g, '1')
        self.assertIn('Unexpected end of input', str(cm.exception))

    def test_unexpected_characters(self):
        g = 'stmnt: expr ";"\nexpr: NUMBER'
        with self.assertRaises(UnexpectedCharacters):
            self.parse(g, '1 ?')

    def test_rule_modifiers_are_rejected(self):
        with self.assertRaises(GrammarError):
            self.make('?a: NUMBER')

    def test_inner_alias_is_rejected(self):
        with self.assertRaises(GrammarError):
            self.make('a: (NUMBER -> x)')

    def test_alias_in_terminal_is_rejected(self):
        with self.assertRaises(GrammarError):
            self.make('a: B\nB: "b" -> x')

    def test_undefined_rule(self):
        with self.assertRaises(GrammarError):
            self.make('a: b')

    def test_first_undefined_symbol_is_reported(self):
        with self.assertRaisesRegex(GrammarError, "'alpha' used but not defined"):
            self.make('a: (alpha | beta) gamma delta epsilon zeta eta theta')

    def test_undefined_ignored_terminals_are_listed_in_order(self):
        with self.assertRaisesRegex(GrammarError, re.escape("Terminals {'DELTA', 'BETA', 'GAMMA'} were marked")):
            self.make('a: NUMBER\n%ignore DELTA, BETA, GAMMA\n')

    def test_error_messages_do_not_depend_on_the_position(self):
        for message, examples in GRAMMAR_ERRORS:
            for example in examples:
                for before in ['', 'a: B\nB: "b"\n', 'B: "b"\na: B\n', 'a: B\n%import common.WS\n']:
                    with self.subTest(example=example, before=before):
                        with self.assertRaisesRegex(GrammarError, re.escape(message)):
                            Larkita(before + example, out_file=os.path.join(self.tmpdir, 'grammar.out'))

    def test_messages_naming_a_token_are_only_given_for_this_token(self):
        for grammar in ['a: B\nB: "b"\nc: B %import\n', 'c: B, B\nB: "b"\n']:
            with self.assertRaises(GrammarError) as cm:
                self.make(grammar)
            self.assertIn('Expecting a value', str(cm.exception))

    def test_alternatives_in_list_of_ignored_terminals_are_rejected(self):
        g = 'a: NUMBER*\nB: "b"\nC: "c"\nD: "d"\n'
        for ignore in ['%ignore B, C | D', '%ignore B, C -> x', '%ignore B, C, D\n    | A']:
            for grammar in [g + ignore, ignore + '\n' + g]:
                with self.assertRaisesRegex(GrammarError, 'cannot contain'):
                    self.make(grammar)
        # An error in the first element cannot be told apart from an error in an alternative of a rule.
        for ignore in ['%ignore B | C, D', '%ignore B -> x, C']:
            with self.assertRaises((GrammarError, UnexpectedToken)):
                self.make(g + ignore)


class TestExampleGrammars(LarkitaTestCase):
    "The example grammars in the directory new-syntax"

    def open(self, name, **options):
        options.setdefault('out_file', os.path.join(self.tmpdir, name + '.out'))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', ConflictWarning)
            return Larkita.open(os.path.join(EXAMPLES, name), **options)

    def test_expr(self):
        parser = self.open('expr.g')
        self.assertEqual(parser.parse('x := (a + 3) * b;'),
                         ((':=', ';'), ('IDENTIFIER', 'x'),
                          ('*', ('+', ('IDENTIFIER', 'a'), ('NUMBER', '3')), ('IDENTIFIER', 'b'))))

    def test_interpreter(self):
        parser = self.open('interpreter.g')
        program = '''
        function fact(n) {
            if (n == 0) return 1; else return n * fact(n - 1);
        }
        s := {x * x : x in {1 .. 10} | x % 2 == 0};  // squares
        print(-s, 2.5, "a");
        '''
        tree = parser.parse(program)
        self.assertEqual(tree[0], 'program')
        function, assignment, call = tree[1:]
        self.assertEqual(function[0], ('function', '(', ')'))
        self.assertEqual(function[1], ('IDENTIFIER', 'fact'))
        self.assertEqual(function[2], (',', ('IDENTIFIER', 'n')))
        self.assertEqual(assignment[1][2][0], ('{', ':', '|', '}'))
        self.assertEqual(call, (';', ('call', ('IDENTIFIER', 'print'),
                                      (',', ('neg', ('IDENTIFIER', 's')), ('FLOAT', '2.5'), ('STRING', '"a"')))))


try:
    import pygments
except ImportError:
    pygments = None


@unittest.skipUnless(pygments, 'Pygments is not installed')
class TestPygmentsLexer(unittest.TestCase):
    "The lexers for highlighting grammars in larkita/pygments_lexer.py"

    def tokens(self, lexer, text):
        from pygments.token import Error
        tokens = [(t, v) for t, v in lexer.get_tokens(text) if v.strip()]
        self.assertEqual([v for t, v in tokens if t in Error], [])
        return tokens

    def test_grammar(self):
        from pygments.token import Comment, Keyword, Name, String
        from larkita.pygments_lexer import LarkitaLexer
        g = ('expr: expr "+" NUMBER    -> "plus"   // a comment\n'
             '    | "-" expr  %prec UMINUS\n'
             '    | NUMBER\n'
             'COMMENT: /#[^\\n]*/\n'
             '%import common.NUMBER, common.WS\n'
             '%ignore WS, COMMENT\n'
             '%left "+"\n'
             '%precedence UMINUS\n')
        tokens = self.tokens(LarkitaLexer(), g)
        self.assertEqual(tokens[0], (Name.Function, 'expr'))
        for expected in [(String, '"+"'), (Name.Variable, 'NUMBER'), (Name.Label, '"plus"'),
                         (Comment.Single, '// a comment'), (String.Regex, '/#[^\\n]*/'),
                         (Name.Variable, 'COMMENT'), (Keyword.Namespace, '%import'), (Keyword.Namespace, '%ignore'),
                         (Keyword.Namespace, '%prec'), (Name.Variable, 'UMINUS'), (Keyword.Namespace, '%left'),
                         (Keyword.Namespace, '%precedence')]:
            self.assertIn(expected, tokens)

    def test_python_with_grammar(self):
        from pygments.token import Name, String
        from larkita.pygments_lexer import PythonLarkitaLexer
        code = 'parser = Larkita(r"""\nstart: A+\nA: "a"\n""")\n'
        tokens = self.tokens(PythonLarkitaLexer(), code)
        self.assertEqual(tokens[0], (Name, 'parser'))
        for expected in [(Name.Function, 'start'), (Name.Variable, 'A'), (String, '"a"')]:
            self.assertIn(expected, tokens)

    def test_entry_points(self):
        import tomllib
        from larkita import pygments_lexer
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'pyproject.toml'), 'rb') as handle:
            entry_points = tomllib.load(handle)['project']['entry-points']['pygments.lexers']
        for name, target in entry_points.items():
            module, class_name = target.split(':')
            self.assertEqual(module, 'larkita.pygments_lexer')
            self.assertIn(name, getattr(pygments_lexer, class_name).aliases)


if __name__ == '__main__':
    unittest.main()
