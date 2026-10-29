"""Builds the callbacks that turn the reductions of the LR parser into abstract syntax trees.

An abstract syntax tree is a nested tuple.  For a rule whose ``AstSpec`` has a head, a reduction
yields ``(head, child_1, ..., child_n)``, where the children are

* the abstract syntax trees of the nonterminals of the rule,
* ``(NAME, text)`` for every named token (string literals are never children), and
* the spliced children of the auxiliary rules that were created for EBNF repetitions.

The auxiliary rules have no ``AstSpec``; their reductions yield a plain list of children.
If the head is None, the rule passes the abstract syntax tree of its only child through.
"""

import json
from typing import Callable, Dict, List, Set, Tuple

from .grammar import Rule, Terminal

_NODE, _TOKEN, _SPLICE = range(3)


def _plan(rule: Rule, aux_names: Set[str]) -> List[Tuple[int, int]]:
    "Returns the positions of the children in the rule's expansion, together with their kind"
    plan = []
    for i, sym in enumerate(rule.expansion):
        if isinstance(sym, Terminal):
            if not sym.filter_out:
                plan.append((i, _TOKEN))
        elif sym.name in aux_names:
            plan.append((i, _SPLICE))
        else:
            plan.append((i, _NODE))
    return plan


def _make_callback(rule: Rule, aux_names: Set[str]) -> Callable:
    plan = _plan(rule, aux_names)

    def collect(children):
        result = []
        for i, kind in plan:
            child = children[i]
            if kind == _NODE:
                result.append(child)
            elif kind == _TOKEN:
                result.append((child.type, child.value))
            elif result:
                result += child
            else:
                result = child   # Reuse the list of the auxiliary rule (avoids quadratic copying)
        return result

    spec = rule.ast
    if spec is None:
        return collect

    if spec.passthrough:
        (i, kind), = plan
        if kind == _TOKEN:
            return lambda children: (children[i].type, children[i].value)
        assert kind == _NODE, rule
        return lambda children: children[i]

    head = spec.head
    return lambda children: (head, *collect(children))


def create_callbacks(rules: List[Rule]) -> Dict[Rule, Callable]:
    aux_names = {rule.origin.name for rule in rules if rule.ast is None}
    return {rule: _make_callback(rule, aux_names) for rule in rules}


def quote(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def format_head(head) -> str:
    if isinstance(head, tuple):
        return '(%s)' % ', '.join(map(quote, head))
    return quote(head)


def describe_ast(rule: Rule, aux_names: Set[str]) -> str:
    """Describes the abstract syntax tree that a reduction by ``rule`` produces, e.g.
    ``("+", ast(expr), ast(product))``.  ``*name`` denotes the spliced children of an auxiliary rule."""
    parts = []
    for i, kind in _plan(rule, aux_names):
        name = rule.expansion[i].name
        if kind == _NODE:
            parts.append('ast(%s)' % name)
        elif kind == _TOKEN:
            parts.append('(%s, text)' % quote(name))
        else:
            parts.append('*' + name)
    spec = rule.ast
    if spec is None:
        return '[%s]' % ', '.join(parts)
    if spec.passthrough:
        return parts[0]
    return '(%s)' % ', '.join([format_head(spec.head)] + parts) if parts else '(%s,)' % format_head(spec.head)
