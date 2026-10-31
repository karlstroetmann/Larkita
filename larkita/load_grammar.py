"""Parses and compiles Larkita grammars into an internal representation.
"""

import hashlib
import os.path
import sys
from collections import namedtuple
from copy import deepcopy
import pkgutil
from ast import literal_eval
from typing import List, Tuple, Union, Callable, Dict, Optional, Sequence, Set

from .utils import bfs, logger, classify_bool, is_id_continue, is_id_start, small_factors, OrderedSet
from .lexer import Token, TerminalDef, PatternStr, PatternRE, Pattern

from .parse_tree_builder import ParseTreeBuilder
from .parser_frontends import ParsingFrontend
from .lr_analysis import LR1Analyzer
from .common import LexerConf
from .grammar import RuleOptions, Rule, Terminal, NonTerminal, Symbol, AstSpec, TOKEN_DEFAULT_PRIORITY
from .utils import classify, dedup_list
from .exceptions import GrammarError, UnexpectedCharacters, UnexpectedToken

from .tree import Tree, SlottedTree as ST
from .visitors import Transformer, Visitor, inline_args, Transformer_InPlace, Transformer_NonRecursive

IMPORT_PATHS = ['grammars']

EXT = '.lark'

_RE_FLAGS = 'imslux'

_TERMINAL_NAMES = {
    '.' : 'DOT',
    ',' : 'COMMA',
    ':' : 'COLON',
    ';' : 'SEMICOLON',
    '+' : 'PLUS',
    '-' : 'MINUS',
    '*' : 'STAR',
    '/' : 'SLASH',
    '\\' : 'BACKSLASH',
    '|' : 'VBAR',
    '?' : 'QMARK',
    '!' : 'BANG',
    '@' : 'AT',
    '#' : 'HASH',
    '$' : 'DOLLAR',
    '%' : 'PERCENT',
    '^' : 'CIRCUMFLEX',
    '&' : 'AMPERSAND',
    '_' : 'UNDERSCORE',
    '<' : 'LESSTHAN',
    '>' : 'MORETHAN',
    '=' : 'EQUAL',
    '"' : 'DBLQUOTE',
    '\'' : 'QUOTE',
    '`' : 'BACKQUOTE',
    '~' : 'TILDE',
    '(' : 'LPAR',
    ')' : 'RPAR',
    '{' : 'LBRACE',
    '}' : 'RBRACE',
    '[' : 'LSQB',
    ']' : 'RSQB',
    '\n' : 'NEWLINE',
    '\r\n' : 'CRLF',
    '\t' : 'TAB',
    ' ' : 'SPACE',
}

# Grammar Parser
TERMINALS = {
    '_LPAR': r'\(',
    '_RPAR': r'\)',
    '_LBRA': r'\[',
    '_RBRA': r'\]',
    'OP': '[+*]|[?](?![a-z_])',
    '_COLON': ':',
    '_COMMA': ',',
    '_OR': r'\|',
    '_DOT': r'\.(?!\.)',
    '_DOTDOT': r'\.\.',
    'TILDE': '~',
    'RULE_MODIFIERS': '(!|![?]?|[?]!?)(?=[_a-z])',
    'RULE': '_?[a-z][_a-z0-9]*',
    'TERMINAL': '_?[A-Z][_A-Z0-9]*',
    'STRING': r'"(\\"|\\\\|[^"\n])*?"i?',
    'REGEXP': r'/(?!/)(\\/|\\\\|[^/])*?/[%s]*' % _RE_FLAGS,
    '_NL': r'(\r?\n)+\s*',
    '_NL_OR': r'(\r?\n)+\s*\|',
    'WS': r'[ \t]+',
    'COMMENT': r'\s*//[^\n]*|\s*#[^\n]*',
    'BACKSLASH': r'\\[ ]*\n',
    '_TO': '->',
    '_IGNORE': r'%ignore',
    '_OVERRIDE': r'%override',
    '_DECLARE': r'%declare',
    '_EXTEND': r'%extend',
    '_IMPORT': r'%import',
    'NUMBER': r'[+-]?\d+',
}

# The meta-grammar uses Lark's tree-shaping conventions, see parse_tree_builder.py
RULES = {
    'start': ['_list'],
    '_list':  ['_item', '_list _item'],
    '_item':  ['rule', 'term', 'ignore', 'ast_ignore', 'import', 'declare', 'override', 'extend', '_NL'],

    'rule': ['rule_modifiers RULE priority _COLON expansions _NL'],
    'rule_modifiers': ['RULE_MODIFIERS',
                       ''],
    'priority': ['_DOT NUMBER',
                 ''],
    'expansions': ['_expansions'],
    '_expansions': ['alias',
                    '_expansions _OR alias',
                    '_expansions _NL_OR alias'],

    # An alternative may end with an alias (-> name or -> "name"), or with the
    # literals that are ignored in its abstract syntax tree (%ignore "(", ")").
    '?alias':     ['expansion _TO nonterminal',
                   'expansion _TO STRING',
                   'expansion ignore_literals',
                   'expansion'],
    'ignore_literals': ['_IGNORE _literals'],
    '_literals': ['STRING', '_literals _COMMA STRING'],

    'expansion': ['_expansion'],

    '_expansion': ['', '_expansion expr'],

    '?expr': ['atom',
              'atom OP',
              'atom TILDE NUMBER',
              'atom TILDE NUMBER _DOTDOT NUMBER',
              ],

    '?atom': ['_LPAR expansions _RPAR',
              'maybe',
              'value'],

    'value': ['terminal',
              'nonterminal',
              'literal',
              'range'],

    'terminal': ['TERMINAL'],
    'nonterminal': ['RULE'],

    '?name': ['RULE', 'TERMINAL'],
    '?symbol': ['terminal', 'nonterminal'],

    'maybe': ['_LBRA expansions _RBRA'],
    'range': ['STRING _DOTDOT STRING'],

    'term': ['TERMINAL _COLON expansions _NL',
             'TERMINAL _DOT NUMBER _COLON expansions _NL'],
    'override': ['_OVERRIDE rule',
                 '_OVERRIDE term'],
    'extend': ['_EXTEND rule',
               '_EXTEND term'],
    'ignore': ['_IGNORE expansions _NL',
               '_IGNORE _ignore_list _NL'],
    # %ignore WS, COMMENT  --  several terminals that are skipped by the lexer.  The elements are
    # expansions without "|", so that the comma after the first one decides which form is meant.
    '_ignore_list': ['expansion _COMMA expansion',
                     '_ignore_list _COMMA expansion'],
    # %ignore: "(", ")"  --  literals that are ignored in the abstract syntax trees of all rules
    'ast_ignore': ['_IGNORE _COLON _literals _NL'],
    'declare': ['_DECLARE _declare_args _NL'],
    'import': ['_IMPORT _import_path _NL',
               '_IMPORT _import_path _LPAR name_list _RPAR _NL',
               '_IMPORT _import_path _TO name _NL'],

    '_import_path': ['import_lib', 'import_rel'],
    'import_lib': ['_import_args'],
    'import_rel': ['_DOT _import_args'],
    '_import_args': ['name', '_import_args _DOT name'],

    'name_list': ['_name_list'],
    '_name_list': ['name', '_name_list _COMMA name'],

    '_declare_args': ['symbol', '_declare_args symbol'],
    'literal': ['REGEXP', 'STRING'],
}

# Value 5 keeps the number of states in the LR parser somewhat minimal
# It isn't optimal, but close to it. See PR #949
SMALL_FACTOR_THRESHOLD = 5
# The Threshold whether repeat via ~ are split up into different rules
# 50 is chosen since it keeps the number of states low and therefore the LR analysis time low,
# while not being to overaggressive and unnecessarily creating rules that might create shift/reduce conflicts.
# (See PR #949)
REPEAT_BREAK_THRESHOLD = 50


def _terminal_kinds(tree) -> Tuple[str, ...]:
    """The full representations of the terminals in ``tree``.  Two trees are equal if their terminals
    have the same names, even if a terminal is a child of the abstract syntax tree in one tree and part
    of the head in the other.  Therefore, the auxiliary rules are cached by the tree together with these
    representations."""
    if isinstance(tree, Terminal):
        return (tree.fullrepr,)
    if isinstance(tree, Tree):
        return tuple(t.fullrepr for t in tree.scan_values(lambda v: isinstance(v, Terminal)))
    return ()


@inline_args
class EBNF_to_BNF(Transformer_InPlace):
    def __init__(self):
        self.new_rules = []
        self.rules_cache = {}
        self.prefix = 'anon'
        self.i = 0

    def _name_rule(self, inner: str):
        new_name = '__%s_%s_%d' % (self.prefix, inner, self.i)
        self.i += 1
        return new_name

    def _add_rule(self, key, name, expansions):
        t = NonTerminal(name)
        self.new_rules.append((name, expansions, None))
        self.rules_cache[key] = t
        return t

    def _add_recurse_rule(self, type_: str, expr: Tree):
        key = (expr, _terminal_kinds(expr))
        try:
            return self.rules_cache[key]
        except KeyError:
            new_name = self._name_rule(type_)
            t = NonTerminal(new_name)
            tree = ST('expansions', [
                ST('expansion', [expr]),
                ST('expansion', [t, expr])
            ])
            return self._add_rule(key, new_name, tree)

    def _add_repeat_rule(self, a, b, target, atom):
        """Generate a rule that repeats target ``a`` times, and repeats atom ``b`` times.

        When called recursively (into target), it repeats atom for x(n) times, where:
            x(0) = 1
            x(n) = a(n) * x(n-1) + b

        Example rule when a=3, b=4:

            new_rule: target target target atom atom atom atom

        """
        key = (a, b, target, atom, _terminal_kinds(atom))
        try:
            return self.rules_cache[key]
        except KeyError:
            new_name = self._name_rule('repeat_a%d_b%d' % (a, b))
            tree = ST('expansions', [ST('expansion', [target] * a + [atom] * b)])
            return self._add_rule(key, new_name, tree)

    def _add_repeat_opt_rule(self, a, b, target, target_opt, atom):
        """Creates a rule that matches atom 0 to (a*n+b)-1 times.

        When target matches n times atom, and target_opt 0 to n-1 times target_opt,

        First we generate target * i followed by target_opt, for i from 0 to a-1
        These match 0 to n*a - 1 times atom

        Then we generate target * a followed by atom * i, for i from 0 to b-1
        These match n*a to n*a + b-1 times atom

        The created rule will not have any shift/reduce conflicts

        Example rule when a=3, b=4:

            new_rule: target_opt
                    | target target_opt
                    | target target target_opt

                    | target target target
                    | target target target atom
                    | target target target atom atom
                    | target target target atom atom atom

        """
        key = (a, b, target, atom, _terminal_kinds(atom), "opt")
        try:
            return self.rules_cache[key]
        except KeyError:
            new_name = self._name_rule('repeat_a%d_b%d_opt' % (a, b))
            tree = ST('expansions', [
                ST('expansion', [target]*i + [target_opt]) for i in range(a)
            ] + [
                ST('expansion', [target]*a + [atom]*i) for i in range(b)
            ])
            return self._add_rule(key, new_name, tree)

    def _generate_repeats(self, rule: Tree, mn: int, mx: int):
        """Generates a rule tree that repeats ``rule`` exactly between ``mn`` to ``mx`` times.
        """
        # For a small number of repeats, we can take the naive approach
        if mx < REPEAT_BREAK_THRESHOLD:
            return ST('expansions', [ST('expansion', [rule] * n) for n in range(mn, mx + 1)])

        # For large repeat values, we break the repetition into sub-rules.
        # We treat ``rule~mn..mx`` as ``rule~mn rule~0..(diff=mx-mn)``.
        # We then use small_factors to split up mn and diff up into values [(a, b), ...]
        # This values are used with the help of _add_repeat_rule and _add_repeat_rule_opt
        # to generate a complete rule/expression that matches the corresponding number of repeats
        mn_target = rule
        for a, b in small_factors(mn, SMALL_FACTOR_THRESHOLD):
            mn_target = self._add_repeat_rule(a, b, mn_target, rule)
        if mx == mn:
            return mn_target

        diff = mx - mn + 1  # We add one because _add_repeat_opt_rule generates rules that match one less
        diff_factors = small_factors(diff, SMALL_FACTOR_THRESHOLD)
        diff_target = rule  # Match rule 1 times
        diff_opt_target = ST('expansion', [])  # match rule 0 times (e.g. up to 1 -1 times)
        for a, b in diff_factors[:-1]:
            diff_opt_target = self._add_repeat_opt_rule(a, b, diff_target, diff_opt_target, rule)
            diff_target = self._add_repeat_rule(a, b, diff_target, rule)

        a, b = diff_factors[-1]
        diff_opt_target = self._add_repeat_opt_rule(a, b, diff_target, diff_opt_target, rule)

        return ST('expansions', [ST('expansion', [mn_target] + [diff_opt_target])])

    def expr(self, rule: Tree, op: Token, *args):
        if op.value == '?':
            empty = ST('expansion', [])
            return ST('expansions', [rule, empty])
        elif op.value == '+':
            # a : b c+ d
            #   -->
            # a : b _c d
            # _c : _c c | c;
            return self._add_recurse_rule('plus', rule)
        elif op.value == '*':
            # a : b c* d
            #   -->
            # a : b _c? d
            # _c : _c c | c;
            new_name = self._add_recurse_rule('star', rule)
            return ST('expansions', [new_name, ST('expansion', [])])
        elif op.value == '~':
            if len(args) == 1:
                mn = mx = int(args[0])
            else:
                mn, mx = map(int, args)
                if mx < mn or mn < 0:
                    raise GrammarError("Bad Range for %s (%d..%d isn't allowed)" % (rule, mn, mx))

            return self._generate_repeats(rule, mn, mx)

        assert False, op

    def maybe(self, rule: Tree):
        return ST('expansions', [rule, ST('expansion', [])])


class SimplifyRule_Visitor(Visitor):

    @staticmethod
    def _flatten(tree: Tree):
        while tree.expand_kids_by_data(tree.data):
            pass

    def expansion(self, tree: Tree):
        # rules_list unpacking
        # a : b (c|d) e
        #  -->
        # a : b c e | b d e
        #
        # In AST terms:
        # expansion(b, expansions(c, d), e)
        #   -->
        # expansions( expansion(b, c, e), expansion(b, d, e) )

        self._flatten(tree)

        for i, child in enumerate(tree.children):
            if isinstance(child, Tree) and child.data == 'expansions':
                tree.data = 'expansions'
                tree.children = [self.visit(ST('expansion', [option if i == j else other
                                                             for j, other in enumerate(tree.children)]))
                                 for option in dedup_list(child.children)]
                self._flatten(tree)
                break

    def alias(self, tree):
        rule, alias_name = tree.children
        if rule.data == 'expansions':
            aliases = []
            for child in tree.children[0].children:
                aliases.append(ST('alias', [child, alias_name]))
            tree.data = 'expansions'
            tree.children = aliases

    def expansions(self, tree: Tree):
        self._flatten(tree)
        # Ensure all children are unique
        if len(set(tree.children)) != len(tree.children):
            tree.children = dedup_list(tree.children)   # dedup is expensive, so try to minimize its use


class RuleTreeToText(Transformer):
    def expansions(self, x):
        return x

    def expansion(self, symbols):
        return symbols, None

    def alias(self, x):
        (expansion, _spec), spec = x
        assert _spec is None and isinstance(spec, AstSpec), (spec, expansion, '-', _spec)
        return expansion, spec


class PrepareAnonTerminals(Transformer_InPlace):
    """Create a unique list of anonymous terminals. Attempt to give meaningful names to them when we add them"""

    def __init__(self, terminals):
        self.terminals = terminals
        self.term_set = {td.name for td in self.terminals}
        self.term_reverse = {td.pattern: td for td in terminals}
        self.i = 0

    @inline_args
    def pattern(self, p):
        # String literals become part of the head of the abstract syntax tree, regular expressions become children
        return Terminal(self._terminal_name(p), filter_out=isinstance(p, PatternStr))

    @inline_args
    def child_pattern(self, p):
        # A string literal inside an inner alternative that could not be expanded becomes a child
        assert isinstance(p, PatternStr), p
        return Terminal(self._terminal_name(p), text=p.value)

    def _terminal_name(self, p):
        value = p.value
        if p in self.term_reverse and p.flags != self.term_reverse[p].pattern.flags:
            raise GrammarError(u'Conflicting flags for the same terminal: %s' % p)

        term_name = None

        if isinstance(p, PatternStr):
            try:
                # If already defined, use the user-defined terminal name
                term_name = self.term_reverse[p].name
            except KeyError:
                # Try to assign an indicative anon-terminal name
                try:
                    term_name = _TERMINAL_NAMES[value]
                except KeyError:
                    if value and is_id_continue(value) and is_id_start(value[0]) and value.upper() not in self.term_set:
                        term_name = value.upper()

                if term_name in self.term_set:
                    term_name = None

        elif isinstance(p, PatternRE):
            if p in self.term_reverse:  # Kind of a weird placement.name
                term_name = self.term_reverse[p].name
        else:
            assert False, p

        if term_name is None:
            term_name = '__ANON_%d' % self.i
            self.i += 1

        if term_name not in self.term_set:
            assert p not in self.term_reverse
            self.term_set.add(term_name)
            termdef = TerminalDef(term_name, p)
            termdef.from_literal = True
            self.term_reverse[p] = termdef
            self.terminals.append(termdef)

        return term_name


def _rfind(s, choices):
    return max(s.rfind(c) for c in choices)


def eval_escaping(s):
    w = ''
    i = iter(s)
    for n in i:
        w += n
        if n == '\\':
            try:
                n2 = next(i)
            except StopIteration:
                raise GrammarError("Literal ended unexpectedly (bad escaping): `%r`" % s)
            if n2 == '\\':
                w += '\\\\'
            elif n2 not in 'Uuxnftr':
                w += '\\'
            w += n2
    w = w.replace('\\"', '"').replace("'", "\\'")

    to_eval = "u'''%s'''" % w
    try:
        s = literal_eval(to_eval)
    except SyntaxError as e:
        raise GrammarError(s, e)

    return s


def _literal_to_pattern(literal):
    assert isinstance(literal, Token)
    v = literal.value
    flag_start = _rfind(v, '/"')+1
    assert flag_start > 0
    flags = v[flag_start:]
    assert all(f in _RE_FLAGS for f in flags), flags

    if literal.type == 'STRING' and '\n' in v:
        raise GrammarError('You cannot put newlines in string literals')

    if literal.type == 'REGEXP' and '\n' in v and 'x' not in flags:
        raise GrammarError('You can only use newlines in regular expressions '
                           'with the `x` (verbose) flag')

    v = v[:flag_start]
    assert v[0] == v[-1] and v[0] in '"/'
    x = v[1:-1]

    s = eval_escaping(x)

    if s == "":
        raise GrammarError("Empty terminals are not allowed (%s)" % literal)

    if literal.type == 'STRING':
        s = s.replace('\\\\', '\\')
        return PatternStr(s, flags, raw=literal.value)
    elif literal.type == 'REGEXP':
        return PatternRE(s, flags, raw=literal.value)
    else:
        assert False, 'Invariant failed: literal.type not in ["STRING", "REGEXP"]'


@inline_args
class PrepareLiterals(Transformer_InPlace):
    def literal(self, literal):
        return ST('pattern', [_literal_to_pattern(literal)])

    def child_literal(self, literal):
        return ST('child_pattern', [_literal_to_pattern(literal)])

    def range(self, start, end):
        assert start.type == end.type == 'STRING'
        start = start.value[1:-1]
        end = end.value[1:-1]
        assert len(eval_escaping(start)) == len(eval_escaping(end)) == 1
        regexp = '[%s-%s]' % (start, end)
        return ST('pattern', [PatternRE(regexp)])


def _make_joined_pattern(regexp, flags_set) -> PatternRE:
    return PatternRE(regexp, ())

class TerminalTreeToPattern(Transformer_NonRecursive):
    def pattern(self, ps):
        p ,= ps
        return p

    def expansion(self, items: List[Pattern]) -> Pattern:
        if not items:
            return PatternStr('')

        if len(items) == 1:
            return items[0]

        pattern = ''.join(i.to_regexp() for i in items)
        return _make_joined_pattern(pattern, {i.flags for i in items})

    def expansions(self, exps: List[Pattern]) -> Pattern:
        if len(exps) == 1:
            return exps[0]

        # Do a bit of sorting to make sure that the longest option is returned
        # (Python's re module otherwise prefers just 'l' when given (l|ll) and both could match)
        exps.sort(key=lambda x: (-x.max_width, -x.min_width, -len(x.value)))

        pattern = '(?:%s)' % ('|'.join(i.to_regexp() for i in exps))
        return _make_joined_pattern(pattern, {i.flags for i in exps})

    def expr(self, args) -> Pattern:
        inner: Pattern
        inner, op = args[:2]
        if op == '~':
            if len(args) == 3:
                op = "{%d}" % int(args[2])
            else:
                mn, mx = map(int, args[2:])
                if mx < mn:
                    raise GrammarError("Bad Range for %s (%d..%d isn't allowed)" % (inner, mn, mx))
                op = "{%d,%d}" % (mn, mx)
        else:
            assert len(args) == 2
        return PatternRE('(?:%s)%s' % (inner.to_regexp(), op), inner.flags)

    def maybe(self, expr):
        return self.expr(expr + ['?'])

    def alias(self, t):
        raise GrammarError("Aliases (->) and %ignore annotations are not allowed in terminals")

    def value(self, v):
        return v[0]


class ValidateSymbols(Transformer_InPlace):
    def value(self, v):
        v ,= v
        assert isinstance(v, (Tree, Symbol))
        return v


def nr_deepcopy_tree(t):
    """Deepcopy tree `t` without recursion"""
    return Transformer_NonRecursive(False).transform(t)


def _literal_text(literal: Token) -> str:
    "The text of a string literal token, e.g. ':=' for the token '\":=\"'"
    assert literal.type == 'STRING', literal
    return _literal_to_pattern(literal).value


def _make_ast_spec(rule_name: str, expansion: Tree, ignore: Set[str], alias: Optional[str]) -> AstSpec:
    """Determines how the abstract syntax tree of an alternative is built (see Claude.md).

    The head is computed statically from the alternative as it is written: it consists of
    all string literals of the alternative that are not ignored, in textual order.  The string
    literals that have been marked by ``_mark_child_literals`` are children instead.
    """
    literals: List[str] = []
    symbols = 0         # number of nonterminals, named terminals, regular expressions and child literals
    is_simple = True    # no EBNF operators and no inner alternatives

    def visit(node):
        nonlocal symbols, is_simple
        if isinstance(node, Symbol):
            symbols += 1
            return
        assert isinstance(node, Tree), node
        if node.data == 'alias':
            raise GrammarError("In rule %s: an alias (->) or an %%ignore annotation can only be given "
                               "at the end of an alternative" % rule_name)
        if node.data == 'literal':
            token ,= node.children
            if token.type == 'STRING':
                text = _literal_text(token)
                if text not in ignore:
                    literals.append(text)
            else:
                symbols += 1
            return
        if node.data in ('child_literal', 'range'):
            symbols += 1
            return
        if node.data in ('expr', 'maybe') or (node.data == 'expansions' and len(node.children) > 1):
            is_simple = False
        for child in node.children:
            if isinstance(child, (Tree, Symbol)):
                visit(child)

    visit(expansion)

    if alias is not None:
        return AstSpec(alias)
    if literals:
        return AstSpec(literals[0] if len(literals) == 1 else tuple(literals))
    if symbols == 1 and is_simple:
        return AstSpec(None)        # pass the abstract syntax tree of the only child through
    return AstSpec(rule_name)


def _expand_alternatives(tree: Tree) -> List[Tree]:
    """Returns the alternatives that the inner alternatives of ``tree`` abbreviate.

    For example, ``expr ("+" | "-") product`` abbreviates the two alternatives ``expr "+" product``
    and ``expr "-" product``, so the literal that has been read becomes the head.  Inner alternatives
    inside repetitions and optional parts are not expanded, since the head of the tuple that collects
    the repeated parts cannot depend on the input.  Their literals become children instead.
    """
    if tree.data == 'expansions':
        return [variant for child in tree.children for variant in _expand_alternatives(child)]
    if tree.data == 'expansion':
        variants: List[List] = [[]]
        for child in tree.children:
            options = (_expand_alternatives(child)
                       if isinstance(child, Tree) and child.data in ('expansion', 'expansions') else [child])
            variants = [variant + [option] for variant in variants for option in options]
        return [ST('expansion', variant) for variant in variants]
    return [tree]


def _mark_child_literals(tree: Tree, ignore: Set[str], inside: bool = False) -> None:
    """Marks the string literals inside the inner alternatives of ``tree`` that are not ignored:
    they become children of the abstract syntax tree (see ``_expand_alternatives``)."""
    for child in tree.children:
        if not isinstance(child, Tree):
            continue
        if child.data == 'literal':
            token ,= child.children
            if inside and token.type == 'STRING' and _literal_text(token) not in ignore:
                child.data = 'child_literal'
        else:
            _mark_child_literals(child, ignore,
                                 inside or (child.data == 'expansions' and len(child.children) > 1))


def _attach_ast_specs(rule_name: str, tree: Tree, ast_ignore: Set[str]) -> None:
    """Replaces every alternative of the rule by ``alias`` nodes that carry the AstSpecs of the
    alternatives that it abbreviates (see ``_expand_alternatives``).  An alternative with an alias
    is not expanded, since its head is the alias.

    SimplifyRule_Visitor later copies the AstSpec to all BNF rules that are derived from the
    alternative, and RuleTreeToText hands it over to the Rule objects.
    """
    assert tree.data == 'expansions'
    while tree.expand_kids_by_data('expansions'):   # alternatives that were added with %extend
        pass

    alternatives = []
    for alternative in tree.children:
        alias = None
        ignore = ast_ignore
        if alternative.data == 'alias':
            expansion, arg = alternative.children
            if isinstance(arg, Tree):
                assert arg.data == 'ignore_literals', arg
                ignore = ast_ignore | {_literal_text(t) for t in arg.children}
            elif isinstance(arg, Token):    # -> "name"
                alias = _literal_text(arg)
            else:                           # -> name
                alias = arg.name
        else:
            expansion = alternative
        if alias is None:
            # The variants are copied, since _mark_child_literals and the later steps change them in place
            variants = [nr_deepcopy_tree(variant) for variant in dedup_list(_expand_alternatives(expansion))]
        else:
            variants = [expansion]
        for variant in variants:
            _mark_child_literals(variant, ignore)
            alternatives.append(ST('alias', [variant, _make_ast_spec(rule_name, variant, ignore, alias)]))
    tree.children = alternatives


class Grammar:

    term_defs: List[Tuple[str, Tuple[Tree, int]]]
    rule_defs: List[Tuple[str, Tree, RuleOptions]]
    ignore: List[str]
    ast_ignore: List[str]
    first_rule: Optional[str]

    def __init__(self, rule_defs: List[Tuple[str, Tree, RuleOptions]], term_defs: List[Tuple[str, Tuple[Tree, int]]],
                 ignore: List[str], ast_ignore: List[str], first_rule: Optional[str]) -> None:
        self.term_defs = term_defs
        self.rule_defs = rule_defs
        self.ignore = ignore
        self.ast_ignore = ast_ignore
        self.first_rule = first_rule

    def compile(self, start, terminals_to_keep) -> Tuple[List[TerminalDef], List[Rule], List[str]]:
        # We change the trees in-place (to support huge grammars)
        # So deepcopy allows calling compile more than once.
        term_defs = [(n, (nr_deepcopy_tree(t), p)) for n, (t, p) in self.term_defs]
        rule_defs = [(n, nr_deepcopy_tree(t), o) for n, t, o in self.rule_defs]

        # ===================
        #  Compile Terminals
        # ===================

        # Convert terminal-trees to strings/regexps

        for name, (term_tree, priority) in term_defs:
            if term_tree is None:  # Terminal added through %declare
                continue
            expansions = list(term_tree.find_data('expansion'))
            if len(expansions) == 1 and not expansions[0].children:
                raise GrammarError("Terminals cannot be empty (%s)" % name)

        transformer = PrepareLiterals() * TerminalTreeToPattern()
        terminals = [TerminalDef(name, transformer.transform(term_tree), priority)
                     for name, (term_tree, priority) in term_defs if term_tree]

        # =================
        #  Compile Rules
        # =================

        # 1. Determine the shape of the abstract syntax tree of every alternative
        ast_ignore = set(self.ast_ignore)
        for name, rule_tree, _options in rule_defs:
            _attach_ast_specs(name, rule_tree, ast_ignore)

        # 2. Pre-process terminals
        anon_tokens_transf = PrepareAnonTerminals(terminals)
        transformer = PrepareLiterals() * ValidateSymbols() * anon_tokens_transf  # Adds to terminals

        # 3. Convert EBNF to BNF (and apply step 2)
        ebnf_to_bnf = EBNF_to_BNF()
        rules = []
        for name, rule_tree, options in rule_defs:
            ebnf_to_bnf.prefix = name
            tree = transformer.transform(rule_tree)
            res: Tree = ebnf_to_bnf.transform(tree)
            rules.append((name, res, options))
        rules += ebnf_to_bnf.new_rules

        assert len(rules) == len({name for name, _t, _o in rules}), "Whoops, name collision"

        # 4. Compile tree to Rule objects
        rule_tree_to_text = RuleTreeToText()

        simplify_rule = SimplifyRule_Visitor()
        compiled_rules: List[Rule] = []
        for rule_content in rules:
            name, tree, options = rule_content
            simplify_rule.visit(tree)
            expansions = rule_tree_to_text.transform(tree)

            for i, (expansion, spec) in enumerate(expansions):
                compiled_rules.append(Rule(NonTerminal(name), expansion, i, options, spec))

        # Remove duplicates of empty rules, throw error for non-empty duplicates
        if len(set(compiled_rules)) != len(compiled_rules):
            duplicates = classify(compiled_rules, lambda x: x)
            for dups in duplicates.values():
                if len(dups) > 1 and dups[0].expansion:
                    raise GrammarError("Rules defined twice: %s\n\n(Might happen due to colliding expansion of optionals: [] or ?)"
                                       % ''.join('\n  * %s' % i for i in dups))

            # Remove duplicates
            compiled_rules = list(OrderedSet(compiled_rules))

        # Filter out unused rules
        while True:
            c = len(compiled_rules)
            used_rules = {s for r in compiled_rules
                            for s in r.expansion
                            if isinstance(s, NonTerminal)
                            and s != r.origin}
            used_rules |= {NonTerminal(s) for s in start}
            compiled_rules, unused = classify_bool(compiled_rules, lambda r: r.origin in used_rules)
            for r in unused:
                logger.debug("Unused rule: %s", r)
            if len(compiled_rules) == c:
                break

        # Filter out unused terminals
        if terminals_to_keep != '*':
            used_terms = {t.name for r in compiled_rules
                                 for t in r.expansion
                                 if isinstance(t, Terminal)}
            terminals, unused = classify_bool(terminals, lambda t: t.name in used_terms or t.name in self.ignore or t.name in terminals_to_keep)
            if unused:
                logger.debug("Unused terminals: %s", [t.name for t in unused])

        return terminals, compiled_rules, self.ignore


PackageResource = namedtuple('PackageResource', 'pkg_name path')


class FromPackageLoader:
    """
    Provides a simple way of creating custom import loaders that load from packages via ``pkgutil.get_data`` instead of using `open`.
    This allows them to be compatible even from within zip files.

    Relative imports are handled, so you can just freely use them.

    pkg_name: The name of the package. You can probably provide `__name__` most of the time
    search_paths: All the path that will be search on absolute imports.
    """

    pkg_name: str
    search_paths: Sequence[str]

    def __init__(self, pkg_name: str, search_paths: Sequence[str]=("", )) -> None:
        self.pkg_name = pkg_name
        self.search_paths = search_paths

    def __repr__(self):
        return "%s(%r, %r)" % (type(self).__name__, self.pkg_name, self.search_paths)

    def __call__(self, base_path: Union[None, str, PackageResource], grammar_path: str) -> Tuple[PackageResource, str]:
        if base_path is None:
            to_try = self.search_paths
        else:
            # Check whether or not the importing grammar was loaded by this module.
            if not isinstance(base_path, PackageResource) or base_path.pkg_name != self.pkg_name:
                # Technically false, but FileNotFound doesn't exist in python2.7, and this message should never reach the end user anyway
                raise IOError()
            to_try = [base_path.path]

        err = None
        for path in to_try:
            full_path = os.path.join(path, grammar_path)
            try:
                text: Optional[bytes] = pkgutil.get_data(self.pkg_name, full_path)
            except IOError as e:
                err = e
                continue
            else:
                return PackageResource(self.pkg_name, full_path), (text.decode() if text else '')

        raise IOError('Cannot find grammar in given paths') from err


stdlib_loader = FromPackageLoader('larkita', IMPORT_PATHS)



def resolve_term_references(term_dict):
    # TODO Solve with transitive closure (maybe)

    while True:
        changed = False
        for name, token_tree in term_dict.items():
            if token_tree is None:  # Terminal added through %declare
                continue
            for exp in token_tree.find_data('value'):
                item ,= exp.children
                if isinstance(item, NonTerminal):
                    raise GrammarError("Rules aren't allowed inside terminals (%s in %s)" % (item, name))
                elif isinstance(item, Terminal):
                    try:
                        term_value = term_dict[item.name]
                    except KeyError:
                        raise GrammarError("Terminal used but not defined: %s" % item.name)
                    assert term_value is not None
                    exp.children[0] = term_value
                    changed = True
                else:
                    assert isinstance(item, Tree)
        if not changed:
            break

    for name, term in term_dict.items():
        if term:    # Not just declared
            for child in term.children:
                ids = [id(x) for x in child.iter_subtrees()]
                if id(term) in ids:
                    raise GrammarError("Recursion in terminal '%s' (recursion is only allowed in rules, not terminals)" % name)



def symbol_from_strcase(s):
    assert isinstance(s, str)
    return Terminal(s, filter_out=s.startswith('_')) if s.isupper() else NonTerminal(s)

@inline_args
class PrepareGrammar(Transformer_InPlace):
    def terminal(self, name):
        return Terminal(str(name))

    def nonterminal(self, name):
        return NonTerminal(name.value)


def _find_used_symbols(tree):
    assert tree.data == 'expansions'
    return {t.name for x in tree.find_data('expansion')
            for t in x.scan_values(lambda t: isinstance(t, Symbol))}


def _get_parser():
    "Returns the (cached) parser for grammar files"
    try:
        return _get_parser.cache
    except AttributeError:
        terminals = [TerminalDef(name, PatternRE(value)) for name, value in TERMINALS.items()]

        rules = [(name.lstrip('?'), x, RuleOptions(expand1=name.startswith('?')))
                for name, x in RULES.items()]
        rules = [Rule(NonTerminal(r), [symbol_from_strcase(s) for s in x.split()], i, o)
                 for r, xs, o in rules for i, x in enumerate(xs)]

        callbacks = ParseTreeBuilder(rules, ST).create_callback()
        import re
        lexer_conf = LexerConf(terminals, re, ['WS', 'COMMENT', 'BACKSLASH'])
        analyzer = LR1Analyzer(rules, 'start')
        assert all(c.resolved for c in analyzer.conflicts), analyzer.conflicts
        _get_parser.cache = ParsingFrontend(lexer_conf, analyzer.parse_table, callbacks, 'basic')
        return _get_parser.cache

GRAMMAR_ERRORS = [
        ('Incorrect type of value', ['a: 1\n']),
        ('Unclosed parenthesis', ['a: (\n']),
        ('Unmatched closing parenthesis', ['a: )\n', 'a: [)\n', 'a: (]\n']),
        ('Expecting rule or terminal definition (missing colon)', ['a\n', 'A\n', 'a->\n', 'A->\n', 'a A\n']),
        ('Illegal name for rules or terminals', ['Aa:\n']),
        ('Unexpected colon', ['a::\n', 'a: b:\n', 'a: B:\n', 'a: "a":\n']),
        ('Misplaced operator', ['a: b??', 'a: b(?)', 'a:+\n', 'a:?\n', 'a:*\n', 'a:|*\n']),
        ('Expecting option ("|") or a new rule or terminal definition', ['a:a\n()\n']),
        ('Terminal names cannot contain dots', ['A.B\n']),
        ('Expecting rule or terminal definition', ['"a"\n']),
        ('%import expects a name', ['%import "a"\n']),
        ('%ignore expects a value', ['%ignore %import\n']),
        # Every example is given as the first statement and after another one, since the error is only
        # recognized if the parser's stack has the same height.
        ('The elements of a list after %ignore cannot contain "|" or "->"',
         [first + example for first in ('', 'A: "a"\n')
          for example in ('%ignore A | B, C\n', '%ignore A -> b, C\n', '%ignore A, B | C\n',
                          '%ignore A, B -> c\n', '%ignore A, B, C | D\n', '%ignore A, B, C -> d\n')]),
    ]

def _translate_parser_exception(parse, e):
        error = e.match_examples(parse, GRAMMAR_ERRORS)
        if error:
            return error
        elif 'STRING' in e.expected:
            return "Expecting a value"

def _parse_grammar(text, name):
    try:
        tree = _get_parser().parse(text + '\n')
    except UnexpectedCharacters as e:
        context = e.get_context(text)
        raise GrammarError("Unexpected input at line %d column %d in %s: \n\n%s" %
                           (e.line, e.column, name, context))
    except UnexpectedToken as e:
        context = e.get_context(text)
        error = _translate_parser_exception(_get_parser().parse, e)
        if error:
            raise GrammarError("%s, at line %s column %s\n\n%s" % (error, e.line, e.column, context))
        raise

    return PrepareGrammar().transform(tree)


def _get_mangle(prefix, aliases, base_mangle=None):
    def mangle(s):
        if s in aliases:
            s = aliases[s]
        else:
            if s[0] == '_':
                s = '_%s__%s' % (prefix, s[1:])
            else:
                s = '%s__%s' % (prefix, s)
        if base_mangle is not None:
            s = base_mangle(s)
        return s
    return mangle

def _mangle_definition_tree(exp, mangle):
    if mangle is None:
        return exp
    exp = deepcopy(exp) # TODO: is this needed?
    for t in exp.iter_subtrees():
        for i, c in enumerate(t.children):
            if isinstance(c, Symbol):
                t.children[i] = c.renamed(mangle)

    return exp

def _make_rule_tuple(modifiers_tree, name, priority_tree, expansions):
    if modifiers_tree.children:
        m ,= modifiers_tree.children
        raise GrammarError("Rule modifiers like '%s' are not supported by Larkita (in rule %s)" % (m, name))

    if priority_tree.children:
        p ,= priority_tree.children
        priority = int(p)
    else:
        priority = None

    return str(name), expansions, RuleOptions(priority=priority)


class Definition:
    def __init__(self, is_term, tree, options=None):
        self.is_term = is_term
        self.tree = tree
        self.options = options

class GrammarBuilder:

    import_paths: List[Union[str, Callable]]
    used_files: Dict[str, str]

    _definitions: Dict[str, Definition]
    _ignore_names: List[str]
    _ast_ignore: List[str]
    _first_rule: Optional[str]

    def __init__(self, import_paths: Optional[List[Union[str, Callable]]]=None, used_files: Optional[Dict[str, str]]=None) -> None:
        self.import_paths = import_paths or []
        self.used_files = used_files or {}

        self._definitions: Dict[str, Definition] = {}
        self._ignore_names: List[str] = []
        self._ast_ignore: List[str] = []
        self._first_rule: Optional[str] = None

    def _grammar_error(self, is_term, msg, *names):
        args = {}
        for i, name in enumerate(names, start=1):
            postfix = '' if i == 1 else str(i)
            args['name' + postfix] = name
            args['type' + postfix] = lowercase_type = ("rule", "terminal")[is_term]
            args['Type' + postfix] = lowercase_type.title()
        raise GrammarError(msg.format(**args))

    def _check_options(self, is_term, options):
        if is_term:
            if options is None:
                options = 1
            elif not isinstance(options, int):
                raise GrammarError("Terminal require a single int as 'options' (e.g. priority), got %s" % (type(options),))
        else:
            if options is None:
                options = RuleOptions()
            elif not isinstance(options, RuleOptions):
                raise GrammarError("Rules require a RuleOptions instance as 'options'")
        return options


    def _define(self, name, is_term, exp, options=None, *, override=False):
        if name in self._definitions:
            if not override:
                self._grammar_error(is_term, "{Type} '{name}' defined more than once", name)
        elif override:
            self._grammar_error(is_term, "Cannot override a nonexisting {type} {name}", name)

        if name.startswith('__'):
            self._grammar_error(is_term, 'Names starting with double-underscore are reserved (Error at {name})', name)

        self._definitions[name] = Definition(is_term, exp, self._check_options(is_term, options))

    def _extend(self, name, is_term, exp, options=None):
        if name not in self._definitions:
            self._grammar_error(is_term, "Can't extend {type} {name} as it wasn't defined before", name)

        d = self._definitions[name]

        if is_term != d.is_term:
            self._grammar_error(is_term, "Cannot extend {type} {name} - one is a terminal, while the other is not.", name)
        if d.tree is None:
            self._grammar_error(is_term, "Can't extend {type} {name} - it is abstract.", name)

        # TODO: think about what to do with 'options'
        base = d.tree

        assert isinstance(base, Tree) and base.data == 'expansions'
        base.children.insert(0, exp)

    def _ignore(self, exp_or_name):
        if isinstance(exp_or_name, str):
            self._ignore_names.append(exp_or_name)
        else:
            assert isinstance(exp_or_name, Tree)
            t = exp_or_name
            if t.data == 'expansion':
                # an element of a list, as in %ignore WS, COMMENT
                t = ST('expansions', [t])
            if t.data == 'expansions' and len(t.children) == 1:
                t2 ,= t.children
                if t2.data=='expansion' and len(t2.children) == 1:
                    item ,= t2.children
                    if item.data == 'value':
                        item ,= item.children
                        if isinstance(item, Terminal):
                            # Keep terminal name, no need to create a new definition
                            self._ignore_names.append(item.name)
                            return

            name = '__IGNORE_%d'% len(self._ignore_names)
            self._ignore_names.append(name)
            self._definitions[name] = Definition(True, t, options=TOKEN_DEFAULT_PRIORITY)

    def _unpack_import(self, stmt, grammar_name):
        if len(stmt.children) > 1:
            path_node, arg1 = stmt.children
        else:
            path_node, = stmt.children
            arg1 = None

        if isinstance(arg1, Tree):  # Multi import
            dotted_path = tuple(path_node.children)
            names = arg1.children
            aliases = dict(zip(names, names))  # Can't have aliased multi import, so all aliases will be the same as names
        else:  # Single import
            dotted_path = tuple(path_node.children[:-1])
            if not dotted_path:
                name ,= path_node.children
                raise GrammarError("Nothing was imported from grammar `%s`" % name)
            name = path_node.children[-1]  # Get name from dotted path
            aliases = {name.value: (arg1 or name).value}  # Aliases if exist

        if path_node.data == 'import_lib':  # Import from library
            base_path = None
        else:  # Relative import
            if grammar_name == '<string>':  # Import relative to script file path if grammar is coded in script
                try:
                    base_file = os.path.abspath(sys.modules['__main__'].__file__)
                except AttributeError:
                    base_file = None
            else:
                base_file = grammar_name  # Import relative to grammar file path if external grammar file
            if base_file:
                if isinstance(base_file, PackageResource):
                    base_path = PackageResource(base_file.pkg_name, os.path.split(base_file.path)[0])
                else:
                    base_path = os.path.split(base_file)[0]
            else:
                base_path = os.path.abspath(os.path.curdir)

        return dotted_path, base_path, aliases

    def _unpack_definition(self, tree, mangle):

        if tree.data == 'rule':
            name, exp, opts = _make_rule_tuple(*tree.children)
            is_term = False
        else:
            name = tree.children[0].value
            opts = int(tree.children[1]) if len(tree.children) == 3 else TOKEN_DEFAULT_PRIORITY # priority
            exp = tree.children[-1]
            is_term = True

        if mangle is not None:
            name = mangle(name)

        exp = _mangle_definition_tree(exp, mangle)
        return name, is_term, exp, opts


    def load_grammar(self, grammar_text: str, grammar_name: str="<?>", mangle: Optional[Callable[[str], str]]=None) -> None:
        tree = _parse_grammar(grammar_text, grammar_name)

        imports: Dict[Tuple[str, ...], Tuple[Optional[str], Dict[str, str]]] = {}

        for stmt in tree.children:
            if stmt.data == 'import':
                dotted_path, base_path, aliases = self._unpack_import(stmt, grammar_name)
                try:
                    import_base_path, import_aliases = imports[dotted_path]
                    assert base_path == import_base_path, 'Inconsistent base_path for %s.' % '.'.join(dotted_path)
                    import_aliases.update(aliases)
                except KeyError:
                    imports[dotted_path] = base_path, aliases

        for dotted_path, (base_path, aliases) in imports.items():
            self.do_import(dotted_path, base_path, aliases, mangle)

        for stmt in tree.children:
            if stmt.data in ('term', 'rule'):
                definition = self._unpack_definition(stmt, mangle)
                self._define(*definition)
                if stmt.data == 'rule' and mangle is None and self._first_rule is None:
                    self._first_rule = definition[0]
            elif stmt.data == 'override':
                r ,= stmt.children
                self._define(*self._unpack_definition(r, mangle), override=True)
            elif stmt.data == 'extend':
                r ,= stmt.children
                self._extend(*self._unpack_definition(r, mangle))
            elif stmt.data == 'ignore':
                # if mangle is not None, we shouldn't apply ignore, since we aren't in a toplevel grammar
                if mangle is None:
                    for item in stmt.children:
                        self._ignore(item)
            elif stmt.data == 'ast_ignore':
                # Like %ignore, this only applies to the toplevel grammar
                if mangle is None:
                    self._ast_ignore.extend(_literal_text(t) for t in stmt.children)
            elif stmt.data == 'declare':
                for symbol in stmt.children:
                    assert isinstance(symbol, Symbol), symbol
                    is_term = isinstance(symbol, Terminal)
                    if not is_term:
                        raise GrammarError("Expecting terminal name to follow %%declare, but got rule name %r" % symbol.name)
                    if mangle is None:
                        name = symbol.name
                    else:
                        name = mangle(symbol.name)
                    self._define(name, is_term, None)
            elif stmt.data == 'import':
                pass
            else:
                assert False, stmt


        term_defs = { name: d.tree
            for name, d in self._definitions.items()
            if d.is_term
        }
        resolve_term_references(term_defs)


    def _remove_unused(self, used):
        def rule_dependencies(symbol):
            try:
                d = self._definitions[symbol]
            except KeyError:
                return []
            if d.is_term:
                return []
            return _find_used_symbols(d.tree)

        _used = set(bfs(used, rule_dependencies))
        self._definitions = {k: v for k, v in self._definitions.items() if k in _used}


    def do_import(self, dotted_path: Tuple[str, ...], base_path: Optional[str], aliases: Dict[str, str], base_mangle: Optional[Callable[[str], str]]=None) -> None:
        assert dotted_path
        mangle = _get_mangle('__'.join(dotted_path), aliases, base_mangle)
        grammar_path = os.path.join(*dotted_path) + EXT
        to_try = self.import_paths + ([base_path] if base_path is not None else []) + [stdlib_loader]
        for source in to_try:
            try:
                if callable(source):
                    joined_path, text = source(base_path, grammar_path)
                else:
                    joined_path = os.path.join(source, grammar_path)
                    with open(joined_path, encoding='utf8') as f:
                        text = f.read()
            except IOError:
                continue
            else:
                h = sha256_digest(text)
                if self.used_files.get(joined_path, h) != h:
                    raise RuntimeError("Grammar file was changed during importing")
                self.used_files[joined_path] = h

                gb = GrammarBuilder(self.import_paths, self.used_files)
                gb.load_grammar(text, joined_path, mangle)
                gb._remove_unused(map(mangle, aliases))
                for name in gb._definitions:
                    if name in self._definitions:
                        raise GrammarError("Cannot import '%s' from '%s': Symbol already defined." % (name, grammar_path))

                self._definitions.update(**gb._definitions)
                break
        else:
            # Search failed. Make Python throw a nice error.
            open(grammar_path, encoding='utf8')
            assert False, "Couldn't import grammar %s, but a corresponding file was found at a place where larkita doesn't search for it" % (dotted_path,)


    def validate(self) -> None:
        for name, d in self._definitions.items():
            exp = d.tree
            if exp is None: # Remaining checks don't apply to abstract rules/terminals (created with %declare)
                continue

            for sym in _find_used_symbols(exp):
                if sym not in self._definitions:
                    self._grammar_error(d.is_term, "{Type} '{name}' used but not defined (in {type2} {name2})", sym, name)

        if not set(self._definitions).issuperset(self._ignore_names):
            raise GrammarError("Terminals %s were marked to ignore but were not defined!" % (set(self._ignore_names) - set(self._definitions)))

    def build(self) -> Grammar:
        self.validate()
        rule_defs = []
        term_defs = []
        for name, d in self._definitions.items():
            if d.is_term:
                term_defs.append((name, (d.tree, d.options)))
            else:
                rule_defs.append((name, d.tree, d.options))
        return Grammar(rule_defs, term_defs, self._ignore_names, self._ast_ignore, self._first_rule)


def load_grammar(grammar: str, source: str, import_paths: List[Union[str, Callable]]) -> Tuple[Grammar, Dict[str, str]]:
    builder = GrammarBuilder(import_paths)
    builder.load_grammar(grammar, source)
    return builder.build(), builder.used_files


def sha256_digest(s: str) -> str:
    """Get the sha256 digest of a string

    Supports the `usedforsecurity` argument for Python 3.9+ to allow running on
    a FIPS-enabled system.
    """
    if sys.version_info >= (3, 9):
        return hashlib.sha256(s.encode('utf8'), usedforsecurity=False).hexdigest()
    else:
        return hashlib.sha256(s.encode('utf8')).hexdigest()
