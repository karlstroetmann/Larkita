"""Construction of canonical LR(1) parse tables.

The automaton is built with Knuth's construction: a state is a set of LR(1) items, i.e. dotted
rules annotated with a set of lookahead tokens.  Two states are only identified if they agree in
all items *and* all lookaheads, so (unlike LALR) no conflicts are introduced by merging states.

Shift/reduce conflicts are resolved in favour of shift.  Reduce/reduce conflicts are resolved in
favour of the rule with the highest priority; if there is no such rule, the conflict is an error.

Optionally, states with the same core are merged afterwards, as long as this does not introduce
new conflicts.  For an LALR(1) grammar the result is the LALR(1) automaton.
"""

from collections import defaultdict
from typing import Callable, Collection, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

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

# Why two states with the same core have been kept apart: a symbol, the actions of both states for
# this symbol (None if a state has no action), and the terminal that the lexer could confuse with it.
Difference = Tuple[str, Optional[Tuple], Optional[Tuple], Optional[str]]


class LR1State:
    __slots__ = ('index', 'kernel', 'items', 'transitions', 'actions', 'merged_from')

    index: int
    kernel: Dict[Item, FrozenSet[str]]
    items: Dict[Item, FrozenSet[str]]       # kernel items first, then the closure items
    transitions: Dict[str, int]             # symbol name -> index of the successor state
    actions: Dict[str, Tuple]
    merged_from: List[int]                  # the indices of the canonical LR(1) states merged into this state

    def __init__(self, index: int, kernel: Dict[Item, FrozenSet[str]]) -> None:
        self.index = index
        self.kernel = kernel
        self.items = {}
        self.transitions = {}
        self.actions = {}
        self.merged_from = [index]


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

    The rule with index 0 is the augmented rule ``$root_<start> : <start>``.  If ``merge_states`` is
    true, states with the same core are merged afterwards, as long as this does not introduce new
    conflicts.  If the parser uses a contextual lexer, ``collision(new, accepted)`` tells whether the
    lexer might split the input differently if the terminal ``new`` is added to the terminals
    ``accepted`` by a state (it returns the colliding terminal or None); such states are not merged
    either.  Afterwards, ``kept_apart`` lists the
    pairs of states that have the same core but could not be merged, together with the reasons.
    """

    def __init__(self, rules: List[Rule], start: str, merge_states: bool = False,
                 collision: Optional[Callable[[str, Collection[str]], Optional[str]]] = None) -> None:
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
        self.lr1_state_count = len(self.states)
        self.merge_states = merge_states
        self.collision = collision
        self.kept_apart: List[Tuple[int, int, List[Difference]]] = []
        if merge_states:
            self._merge_states()
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

    @staticmethod
    def _signature(state: LR1State, block: List[int]) -> Dict[str, Tuple]:
        "The actions of the state, where a shift or goto refers to the block of its target"
        return {name: (Shift, block[arg]) if action is Shift else (Reduce, id(arg))
                for name, (action, arg) in state.actions.items()}

    @staticmethod
    def _compatible(signature: Dict[str, Tuple], merged: Dict[str, Tuple]) -> bool:
        "Two sets of actions are compatible if they agree on every symbol that both of them handle"
        return all(merged.get(name, action) == action for name, action in signature.items())

    def _terminals(self, state: LR1State) -> FrozenSet[str]:
        "The terminals for which the state has an action, i.e. the terminals the contextual lexer accepts"
        return frozenset(name for name in state.actions if name not in self.rules_by_origin)

    def _collisions(self, new: Collection[str], accepted: FrozenSet[str]) -> List[Tuple[str, str]]:
        "The pairs of a terminal of ``new`` and an accepted (or ignored) terminal that the lexer could confuse"
        result = []
        if self.collision is not None:
            for name in sorted(new):
                other = self.collision(name, accepted)
                if other is not None:
                    result.append((name, other))
        return result

    def _mergeable(self, terminals: List[FrozenSet[str]], members1: List[int], terminals1: FrozenSet[str],
                   members2: List[int], terminals2: FrozenSet[str]) -> bool:
        "Tests whether merging two groups of states leaves the lexer of every state unchanged"
        return (all(not self._collisions(terminals2 - terminals[i], terminals[i]) for i in members1) and
                all(not self._collisions(terminals1 - terminals[i], terminals[i]) for i in members2))

    def _merge_states(self) -> None:
        """Merges states with the same core, as long as this does not introduce new conflicts.

        The states are partitioned into blocks.  Initially, all states with the same core form one
        block.  A block is split as long as it contains states whose actions disagree for some symbol;
        as shifts and gotos are compared via the blocks of their targets, merged states also have
        merged successors.  States are not merged either if this might change how the contextual
        lexer splits the input.  As the splitting is greedy, blocks with the same core that turn out
        to be compatible are joined afterwards.  Finally, every block becomes a state.

        Merging only adds reductions for lookaheads that are errors in some of the merged states.
        Therefore, the parser accepts the same strings and builds the same abstract syntax trees, but
        it may perform some reductions before it detects a syntax error.
        """
        states = self.states
        terminals = [self._terminals(state) for state in states]
        cores: Dict[FrozenSet[Item], int] = {}
        block = [cores.setdefault(frozenset(state.kernel), len(cores)) for state in states]
        while True:
            members: Dict[int, List[LR1State]] = defaultdict(list)
            for state in states:
                members[block[state.index]].append(state)
            new_block = [0] * len(states)
            count = 0
            for b in sorted(members):
                parts: List[Tuple[Dict[str, Tuple], List[int], FrozenSet[str]]] = []
                for state in members[b]:
                    i = state.index
                    signature = self._signature(state, block)
                    for k, (merged, indices, merged_terminals) in enumerate(parts):
                        if (self._compatible(signature, merged) and
                                self._mergeable(terminals, indices, merged_terminals, [i], terminals[i])):
                            merged.update(signature)
                            indices.append(i)
                            parts[k] = (merged, indices, merged_terminals | terminals[i])
                            break
                    else:
                        parts.append((signature, [i], terminals[i]))
                for _, indices, _ in parts:
                    for i in indices:
                        new_block[i] = count
                    count += 1
            block = new_block
            if count == len(members):
                break

        joined = True
        while joined:
            joined = False
            merged_actions: Dict[int, Dict[str, Tuple]] = {}
            block_members: Dict[int, List[int]] = defaultdict(list)
            blocks_of_core: Dict[FrozenSet[Item], List[int]] = defaultdict(list)
            for state in states:
                b = block[state.index]
                if b not in merged_actions:
                    merged_actions[b] = {}
                    blocks_of_core[frozenset(state.kernel)].append(b)
                merged_actions[b].update(self._signature(state, block))
                block_members[b].append(state.index)
            block_terminals = {b: frozenset().union(*(terminals[i] for i in ms)) for b, ms in block_members.items()}
            for blocks in blocks_of_core.values():
                pairs = [(b1, b2) for k, b1 in enumerate(blocks) for b2 in blocks[k+1:]]
                for b1, b2 in pairs:
                    if (self._compatible(merged_actions[b1], merged_actions[b2]) and
                            self._mergeable(terminals, block_members[b1], block_terminals[b1],
                                            block_members[b2], block_terminals[b2])):
                        block = [b1 if b == b2 else b for b in block]
                        joined = True
                        break
                if joined:
                    break

        # The merged states are numbered in the order of their first canonical state.
        number: Dict[int, int] = {}
        new_index = [number.setdefault(b, len(number)) for b in block]
        merged_states: List[LR1State] = []
        for state in states:
            i = new_index[state.index]
            if i == len(merged_states):
                merged_states.append(LR1State(i, {}))
                merged_states[i].merged_from = []
            new = merged_states[i]
            new.merged_from.append(state.index)
            for item, lookaheads in state.kernel.items():
                new.kernel[item] = new.kernel.get(item, frozenset()) | lookaheads
            for item, lookaheads in state.items.items():
                new.items[item] = new.items.get(item, frozenset()) | lookaheads
            for name, target in state.transitions.items():
                new.transitions[name] = new_index[target]
            for name, (action, arg) in state.actions.items():
                new.actions[name] = (Shift, new_index[arg]) if action is Shift else (action, arg)

        conflicts: List[Conflict] = []
        seen: Set[Tuple] = set()
        for c in self.conflicts:
            shift_state = None if c.shift_state is None else new_index[c.shift_state]
            chosen = (Shift, new_index[c.chosen[1]]) if c.chosen[0] is Shift else c.chosen
            key = (new_index[c.state], c.terminal, tuple(id(r) for r in c.rules), shift_state)
            if key not in seen:
                seen.add(key)
                conflicts.append(Conflict(new_index[c.state], c.terminal, c.rules, shift_state,
                                          chosen, c.resolved, c.reason))
        conflicts.sort(key=lambda c: c.state)

        # Explain why states with the same core have been kept apart.  As every block is compatible
        # with the union of its members, comparing the merged states suffices.
        states_of_core: Dict[FrozenSet[Item], List[LR1State]] = defaultdict(list)
        for state in merged_states:
            states_of_core[frozenset(state.kernel)].append(state)
        for group in states_of_core.values():
            for k, s in enumerate(group):
                for t in group[k+1:]:
                    differences: List[Difference] = [
                        (name, s.actions[name], t.actions[name], None)
                        for name in sorted(s.actions.keys() & t.actions.keys())
                        if s.actions[name] != t.actions[name]]
                    ts, tt = self._terminals(s), self._terminals(t)
                    for name, other in self._collisions(tt - ts, ts):
                        differences.append((name, None, t.actions[name], other))
                    for name, other in self._collisions(ts - tt, tt):
                        differences.append((name, s.actions[name], None, other))
                    self.kept_apart.append((s.index, t.index, differences))

        self.states = merged_states
        self.conflicts = conflicts
        self.end_state = new_index[self.end_state]
