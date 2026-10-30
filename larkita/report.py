"""Writes the output file that documents the LR(1) automaton.

The file lists the rules (with the shape of the abstract syntax tree that every rule produces),
the conflicts, and all states.  Every state shows its kernel and closure items in the form

    A → α • β    { lookahead tokens }

followed by its actions and gotos.  String literals are shown as they are written in the grammar.
If the states have been merged, the file also explains which states could not be merged.
"""

from typing import Dict, Iterable, List, Optional, Tuple

from .ast_builder import describe_ast
from .grammar import Rule
from .lr_analysis import LR1Analyzer, Conflict, Shift, END


class _Formatter:
    def __init__(self, analyzer: LR1Analyzer, terminal_names: Dict[str, str]) -> None:
        self.analyzer = analyzer
        self.terminal_names = terminal_names
        self.rule_number = {id(rule): i for i, rule in enumerate(analyzer.rules)}

    def symbol(self, name: str) -> str:
        return self.terminal_names.get(name, name)

    @staticmethod
    def sort_key(row: List[str]):
        "Sorts the rows of the action table by symbol, with $END last"
        return (row[0] == END, row[0])

    def lookaheads(self, terminals: Iterable[str]) -> str:
        names = sorted(self.symbol(t) for t in terminals if t != END)
        if END in terminals:
            names.append(END)
        return '{ %s }' % ', '.join(names)

    def rule(self, rule: Rule) -> str:
        rhs = ' '.join(self.symbol(sym.name) for sym in rule.expansion)
        return '%s → %s' % (rule.origin.name, rhs or 'ε')

    def item(self, rule: Rule, dot: int) -> str:
        names = [self.symbol(sym.name) for sym in rule.expansion]
        return '%s → %s' % (rule.origin.name, ' '.join(names[:dot] + ['•'] + names[dot:]))

    def number(self, rule: Rule) -> str:
        return '(%d)' % self.rule_number[id(rule)]

    def conflict(self, c: Conflict, with_state: bool = True) -> str:
        options = []
        if c.shift_state is not None:
            options.append('shift and go to state %d' % c.shift_state)
        options += ['reduce using rule %s %s' % (self.number(r), self.rule(r)) for r in c.rules]
        chosen_action, arg = c.chosen
        if not c.resolved:
            status = 'NOT RESOLVED (this is an error)'
        elif chosen_action is Shift:
            status = c.reason
        else:
            status = '%s: reduce using rule %s' % (c.reason, self.number(arg))
        where = 'State %d, ' % c.state if with_state else ''
        lines = ['%s%s conflict on %s, %s' % (where, c.kind, self.symbol(c.terminal), status)]
        lines += ['    - ' + option for option in options]
        return '\n'.join(lines)

    def action(self, name: str, action: Optional[Tuple], other: Optional[str]) -> str:
        "Describes what a state does for the symbol ``name``, e.g. 'reduces using rule (3) a → b'"
        if action is None:
            assert other is not None
            return 'does not accept %s (collides with %s)' % (self.symbol(name), self.symbol(other))
        kind, arg = action
        if kind is not Shift:
            return 'reduces using rule %s %s' % (self.number(arg), self.rule(arg))
        if name in self.analyzer.rules_by_origin:
            return 'goes to state %d' % arg
        return 'shifts and goes to state %d' % arg

    def merged_states(self) -> List[str]:
        a = self.analyzer
        out = ['States with the same core have been merged, unless this would cause',
               'a conflict: %d LR(1) states have been merged into %d states.' % (a.lr1_state_count, len(a.states))]
        if not a.kept_apart:
            return out + ['All states with the same core have been merged, so this is the',
                          'LALR(1) automaton.', '']
        # A pair whose actions only differ in the targets of shifts and gotos has been kept apart
        # because its successors have been kept apart.
        causes = [pair for pair in a.kept_apart
                  if any(s is None or t is None or s[0] is not Shift or t[0] is not Shift
                         for _, s, t, _ in pair[2])]
        consequences = [pair for pair in a.kept_apart if pair not in causes]
        if causes:
            out += ['', 'The following states have the same core, but they have been kept',
                    'apart.  Either merging them would cause a conflict, or one of them',
                    'accepts a token that collides with a token of the other one, i.e.',
                    'the scanner could read the same text as either of these tokens.']
        for s, t, differences in causes:
            out += ['', 'States %d and %d' % (s, t)]
            for name, action_s, action_t, other in differences:
                out += ['    on %s:' % self.symbol(name),
                        '        state %d %s' % (s, self.action(name, action_s, other)),
                        '        state %d %s' % (t, self.action(name, action_t, other))]
        if consequences:
            out += ['', 'The following states have the same core, but they have been kept',
                    'apart, because their successors have been kept apart:', '']
            pairs = ['%d and %d' % (s, t) for s, t, _ in consequences]
            lines = ['   ']
            for pair in pairs:
                if len(lines[-1]) + len(pair) > 66:
                    lines.append('   ')
                lines[-1] += ' %s,' % pair
            out += lines[:-1] + [lines[-1].rstrip(',')]
        return out + ['']


def _table(rows: List[List[str]], indent: str) -> List[str]:
    "Formats the rows so that their columns are aligned"
    if not rows:
        return []
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]) - 1)]
    lines = []
    for row in rows:
        cells = [cell.ljust(width) for cell, width in zip(row, widths)] + [row[-1]]
        lines.append((indent + '  '.join(cells)).rstrip())
    return lines


def format_report(analyzer: LR1Analyzer, terminal_names: Dict[str, str], source: str) -> str:
    f = _Formatter(analyzer, terminal_names)
    aux_names = {rule.origin.name for rule in analyzer.rules[1:] if rule.ast is None}
    errors = [c for c in analyzer.conflicts if not c.resolved]

    if analyzer.merge_states:
        title = 'LR(1) automaton with merged states generated by Larkita'
        states = '%d (merged from %d LR(1) states)' % (len(analyzer.states), analyzer.lr1_state_count)
    else:
        title, states = 'Canonical LR(1) automaton generated by Larkita', str(len(analyzer.states))
    out = [title,
           '',
           'Grammar:      %s' % source,
           'Start symbol: %s' % analyzer.start,
           'States:       %s' % states,
           'Conflicts:    %d (%d unresolved)' % (len(analyzer.conflicts), len(errors)),
           '',
           '',
           'Rules',
           '=====',
           '',
           'Every rule is followed by the abstract syntax tree that a reduction produces.',
           '"*name" stands for the list of children collected by the auxiliary rule "name".',
           '"text" stands for the text of a named token.',
           '']
    rows = [[f.number(rule), f.rule(rule), '⇒ ' + describe_ast(rule, aux_names)]
            for rule in analyzer.rules[1:]]
    out += _table([[f.number(analyzer.root_rule), f.rule(analyzer.root_rule), '']] + rows, '  ')

    out += ['', '', 'Conflicts', '=========', '']
    if analyzer.conflicts:
        for c in analyzer.conflicts:
            out += [f.conflict(c), '']
    else:
        out += ['There are no conflicts.', '']

    if analyzer.merge_states:
        out += ['', 'Merged states', '=============', ''] + f.merged_states()

    out += ['', 'States', '======', '',
            'Every state lists its items with their lookahead tokens; closure items are marked with "+".',
            'Rules are referred to by their numbers in the list of rules.']
    for state in analyzer.states:
        header = 'State %d' % state.index
        if len(state.merged_from) > 1:
            header += '   (merged from the LR(1) states %s)' % ', '.join(map(str, state.merged_from))
        out += ['', '', header, '']
        rows = []
        for (r, d), lookaheads in state.items.items():
            marker = '' if (r, d) in state.kernel else '+'
            rows.append([marker, f.number(analyzer.rules[r]), f.item(analyzer.rules[r], d), f.lookaheads(lookaheads)])
        out += _table(rows, '  ')
        out.append('')

        shifts, reduces, gotos = [], [], []
        for name, (action, arg) in state.actions.items():
            if action is Shift:
                if name in analyzer.rules_by_origin:
                    gotos.append([name, 'go to state %d' % arg])
                else:
                    shifts.append([f.symbol(name), 'shift and go to state %d' % arg])
            else:
                reduces.append([f.symbol(name), 'reduce using rule %s %s' % (f.number(arg), f.rule(arg))])
        if state.index == analyzer.end_state:
            reduces.append([END, 'accept'])
        rows = sorted(shifts, key=f.sort_key) + sorted(reduces, key=f.sort_key)
        if gotos:
            rows += [['', '']] + sorted(gotos)
        out += _table(rows, '    ')

        conflicts = [c for c in analyzer.conflicts if c.state == state.index]
        if conflicts:
            out.append('')
            for c in conflicts:
                out += ['    ' + line for line in f.conflict(c, with_state=False).split('\n')]

    return '\n'.join(out) + '\n'


def write_report(path: str, analyzer: LR1Analyzer, terminal_names: Dict[str, str], source: str) -> None:
    with open(path, 'w', encoding='utf8') as f:
        f.write(format_report(analyzer, terminal_names, source))
