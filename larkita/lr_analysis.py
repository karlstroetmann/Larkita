"""Construction of canonical LR(1) parse tables.

The automaton is built with Knuth's construction: a state is a set of LR(1) items, i.e. dotted
rules annotated with a set of lookahead tokens.  Two states are only identified if they agree in
all items *and* all lookaheads, so (unlike LALR) no conflicts are introduced by merging states.

Shift/reduce conflicts are resolved in favour of shift.  Reduce/reduce conflicts are resolved in
favour of the rule with the highest priority; if there is no such rule, the conflict is an error.
"""

from collections import defaultdict
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from .grammar import Rule, NonTerminal, Symbol
from .exceptions import GrammarError

END = '$END'


class Action:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return self.name

Shift = Action('Shift')
Reduce = Action('Reduce')


class ParseTable:
    """The action and goto table.

    ``states[s][X]`` is either ``(Shift, t)`` or ``(Reduce, rule)``.  If ``X`` is a nonterminal,
    the entry ``(Shift, t)`` is the goto of state ``s`` for ``X``.  The parser accepts when it
    reaches ``end_state`` while the lookahead is ``$END``.
    """
    def __init__(self, states: List[Dict[str, Tuple]], start_state: int, end_state: int) -> None:
        self.states = states
        self.start_state = start_state
        self.end_state = end_state


Item = Tuple[int, int]   # (index of the rule, position of the dot)


class LR1State:
    __slots__ = ('index', 'kernel', 'items', 'transitions', 'actions')

    index: int
    kernel: Dict[Item, FrozenSet[str]]
    items: Dict[Item, FrozenSet[str]]       # kernel items first, then the closure items
    transitions: Dict[str, int]             # symbol name -> index of the successor state
    actions: Dict[str, Tuple]

    def __init__(self, index: int, kernel: Dict[Item, FrozenSet[str]]) -> None:
        self.index = index
        self.kernel = kernel
        self.items = {}
        self.transitions = {}
        self.actions = {}


class Conflict:
    """A conflict in state ``state`` for the lookahead ``terminal``.

    ``rules`` are the rules that could be reduced, ``shift_state`` is the state the parser
    could shift to (or None), and ``chosen`` is the action that was put into the table.
    """
    def __init__(self, state: int, terminal: str, rules: List[Rule], shift_state: Optional[int],
                 chosen: Tuple, resolved: bool, reason: str) -> None:
        self.state = state
        self.terminal = terminal
        self.rules = rules
        self.shift_state = shift_state
        self.chosen = chosen
        self.resolved = resolved
        self.reason = reason

    @property
    def kind(self) -> str:
        if len(self.rules) > 1:
            return 'shift/reduce/reduce' if self.shift_state is not None else 'reduce/reduce'
        return 'shift/reduce'

    def __repr__(self):
        return '<%s conflict in state %d on %s>' % (self.kind, self.state, self.terminal)


def _first_sets(rules: List[Rule]) -> Tuple[Dict[str, Set[str]], Set[str]]:
    "Computes FIRST (over terminal names) for every nonterminal, and the set of nullable nonterminals"
    first: Dict[str, Set[str]] = defaultdict(set)
    nullable: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for rule in rules:
            origin = rule.origin.name
            target = first[origin]
            for sym in rule.expansion:
                if sym.is_term:
                    if sym.name not in target:
                        target.add(sym.name)
                        changed = True
                    break
                f = first[sym.name]
                if not f <= target:
                    target |= f
                    changed = True
                if sym.name not in nullable:
                    break
            else:
                if origin not in nullable:
                    nullable.add(origin)
                    changed = True
    return first, nullable


class LR1Analyzer:
    """Builds the canonical LR(1) automaton and the parse table for ``rules`` and the start symbol ``start``.

    The rule with index 0 is the augmented rule ``$root_<start> : <start>``.
    """

    def __init__(self, rules: List[Rule], start: str) -> None:
        self.start = start
        self.root_rule = Rule(NonTerminal('$root_' + start), [NonTerminal(start)])
        self.rules: List[Rule] = [self.root_rule] + list(rules)

        self.rules_by_origin: Dict[str, List[int]] = defaultdict(list)
        for i, rule in enumerate(self.rules):
            self.rules_by_origin[rule.origin.name].append(i)

        if len(set(self.rules)) != len(self.rules):
            seen: Set[Rule] = set()
            duplicates = [r for r in self.rules if r in seen or seen.add(r)]   # type: ignore[func-returns-value]
            raise GrammarError("Rules defined twice: %s" % ', '.join(str(r) for r in duplicates))
        if start not in self.rules_by_origin:
            raise GrammarError("The start symbol %r is not defined" % start)
        for rule in self.rules:
            for sym in rule.expansion:
                if not sym.is_term and sym.name not in self.rules_by_origin:
                    raise GrammarError("Using an undefined rule: %s" % sym.name)

        self.first, self.nullable = _first_sets(self.rules)

        # For every item whose dot is in front of a nonterminal B, i.e. [A : alpha . B beta],
        # store B, FIRST(beta), and whether beta is nullable.
        self._after_dot: Dict[Item, Tuple[str, FrozenSet[str], bool]] = {}
        for r, rule in enumerate(self.rules):
            expansion = rule.expansion
            for d, sym in enumerate(expansion):
                if not sym.is_term:
                    first, nullable = self._first_of_sequence(expansion[d+1:])
                    self._after_dot[(r, d)] = (sym.name, frozenset(first), nullable)

        self.states: List[LR1State] = []
        self.conflicts: List[Conflict] = []
        self._build_states()
        self.end_state = self.states[0].transitions[start]
        self._build_actions()
        self.parse_table = ParseTable([state.actions for state in self.states], 0, self.end_state)

    def _first_of_sequence(self, symbols: Sequence[Symbol]) -> Tuple[Set[str], bool]:
        result: Set[str] = set()
        for sym in symbols:
            if sym.is_term:
                result.add(sym.name)
                return result, False
            result |= self.first[sym.name]
            if sym.name not in self.nullable:
                return result, False
        return result, True

    def _closure(self, kernel: Dict[Item, FrozenSet[str]]) -> Dict[Item, Set[str]]:
        items = {item: set(la) for item, la in kernel.items()}
        todo = list(items)
        after_dot = self._after_dot
        rules_by_origin = self.rules_by_origin
        while todo:
            item = todo.pop()
            try:
                name, first, nullable = after_dot[item]
            except KeyError:
                continue
            lookaheads = first | items[item] if nullable else first
            for r in rules_by_origin[name]:
                new_item = (r, 0)
                current = items.get(new_item)
                if current is None:
                    items[new_item] = set(lookaheads)
                    todo.append(new_item)
                elif not lookaheads <= current:
                    current |= lookaheads
                    todo.append(new_item)
        return items

    def _build_states(self) -> None:
        index: Dict[FrozenSet, int] = {}

        def get_state(kernel: Dict[Item, FrozenSet[str]]) -> int:
            key = frozenset(kernel.items())
            try:
                return index[key]
            except KeyError:
                i = index[key] = len(self.states)
                self.states.append(LR1State(i, kernel))
                return i

        get_state({(0, 0): frozenset([END])})
        i = 0
        while i < len(self.states):
            state = self.states[i]
            i += 1
            items = self._closure(state.kernel)
            kernel_items = sorted(state.kernel)
            closure_items = sorted(item for item in items if item not in state.kernel)
            state.items = {item: frozenset(items[item]) for item in kernel_items + closure_items}

            successors: Dict[str, Dict[Item, FrozenSet[str]]] = {}
            for (r, d), lookaheads in state.items.items():
                expansion = self.rules[r].expansion
                if d < len(expansion):
                    successors.setdefault(expansion[d].name, {})[(r, d+1)] = lookaheads
            for name, kernel in successors.items():
                state.transitions[name] = get_state(kernel)

    def _build_actions(self) -> None:
        for state in self.states:
            actions: Dict[str, Tuple] = {name: (Shift, target) for name, target in state.transitions.items()}

            reductions: Dict[str, List[Rule]] = defaultdict(list)
            for (r, d), lookaheads in state.items.items():
                rule = self.rules[r]
                if d == len(rule.expansion) and r != 0:   # [$root : start .] means accept
                    for terminal in lookaheads:
                        reductions[terminal].append(rule)

            for terminal in sorted(reductions):
                rules = reductions[terminal]
                rule = rules[0]
                resolved, reason = True, ''
                if len(rules) > 1:
                    top = max(r.options.priority or 0 for r in rules)
                    best = [r for r in rules if (r.options.priority or 0) == top]
                    rule = best[0]
                    if len(best) == 1:
                        reason = 'resolved by priority'
                    else:
                        resolved, reason = False, 'not resolved'

                if terminal in actions:
                    if resolved:
                        reason = 'resolved as shift'
                    self.conflicts.append(Conflict(state.index, terminal, rules, actions[terminal][1],
                                                   actions[terminal], resolved, reason))
                else:
                    actions[terminal] = (Reduce, rule)
                    if len(rules) > 1:
                        self.conflicts.append(Conflict(state.index, terminal, rules, None,
                                                       actions[terminal], resolved, reason))

            state.actions = actions
