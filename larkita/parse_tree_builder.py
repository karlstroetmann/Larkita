"""Builds the parse trees of grammar files (internal).

The meta-grammar uses the tree-shaping conventions of Lark: rules whose name starts with ``?``
are replaced by their child if they have only one, rules whose name starts with ``_`` are inlined
into their parent, and terminals whose name starts with ``_`` are filtered out.
"""

from typing import Callable, Dict, List

from .grammar import Rule, Terminal


def _should_expand(sym):
    return not sym.is_term and sym.name.startswith('_')


class ParseTreeBuilder:
    def __init__(self, rules: List[Rule], tree_class) -> None:
        self.rules = rules
        self.tree_class = tree_class

    def _make_callback(self, rule: Rule) -> Callable:
        tree_class = self.tree_class
        name = rule.origin.name
        expand1 = rule.options.expand1
        to_include = [(i, _should_expand(sym)) for i, sym in enumerate(rule.expansion)
                      if not (isinstance(sym, Terminal) and sym.filter_out)]

        def callback(children):
            filtered = []
            for i, to_expand in to_include:
                if to_expand:
                    filtered += children[i].children
                else:
                    filtered.append(children[i])
            if expand1 and len(filtered) == 1:
                return filtered[0]
            return tree_class(name, filtered)

        return callback

    def create_callback(self) -> Dict[Rule, Callable]:
        return {rule: self._make_callback(rule) for rule in self.rules}
