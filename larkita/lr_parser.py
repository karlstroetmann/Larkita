"""The table-driven LR parser."""

from typing import Any, Callable, Dict, List

from .exceptions import UnexpectedToken
from .lexer import Token, LexerThread
from .lr_analysis import ParseTable, Shift, END
from .grammar import Rule


class ParserState:
    __slots__ = 'parse_table', 'callbacks', 'state_stack', 'value_stack'

    parse_table: ParseTable
    callbacks: Dict[Rule, Callable]
    state_stack: List[int]
    value_stack: list

    def __init__(self, parse_table: ParseTable, callbacks: Dict[Rule, Callable]) -> None:
        self.parse_table = parse_table
        self.callbacks = callbacks
        self.state_stack = [parse_table.start_state]
        self.value_stack = []

    @property
    def position(self) -> int:
        "The current state of the LR automaton (used by the contextual lexer)"
        return self.state_stack[-1]

    # Necessary for match_examples() to work
    def __eq__(self, other) -> bool:
        if not isinstance(other, ParserState):
            return NotImplemented
        return len(self.state_stack) == len(other.state_stack) and self.position == other.position

    def feed_token(self, token: Token, is_end=False) -> Any:
        state_stack = self.state_stack
        value_stack = self.value_stack
        states = self.parse_table.states
        end_state = self.parse_table.end_state
        callbacks = self.callbacks

        while True:
            state = state_stack[-1]
            try:
                action, arg = states[state][token.type]
            except KeyError:
                expected = {s for s in states[state].keys() if s.isupper()}
                if state == end_state and not is_end:
                    expected.add(END)
                raise UnexpectedToken(token, expected, state=self)

            if action is Shift:
                # shift once and return
                assert not is_end
                state_stack.append(arg)
                value_stack.append(token)
                return
            else:
                # reduce+shift as many times as necessary
                rule = arg
                size = len(rule.expansion)
                if size:
                    s = value_stack[-size:]
                    del state_stack[-size:]
                    del value_stack[-size:]
                else:
                    s = []

                value = callbacks[rule](s)

                _action, new_state = states[state_stack[-1]][rule.origin.name]
                assert _action is Shift
                state_stack.append(new_state)
                value_stack.append(value)

                if is_end and new_state == end_state:
                    return value


class LRParser:
    def __init__(self, parse_table: ParseTable, callbacks: Dict[Rule, Callable]) -> None:
        self.parse_table = parse_table
        self.callbacks = callbacks

    def parse(self, lexer: LexerThread) -> Any:
        state = ParserState(self.parse_table, self.callbacks)
        token = None
        for token in lexer.lex(state):
            state.feed_token(token)

        # The end state is only reached by a goto, so after the last shift we always have to reduce
        end_token = Token.new_borrow_pos(END, '', token) if token else Token(END, '', 0, 1, 1)
        return state.feed_token(end_token, True)
