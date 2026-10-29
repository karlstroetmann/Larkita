from typing import Any, Callable, Collection, Dict

from .common import LexerConf
from .exceptions import ConfigurationError, UnexpectedInput
from .grammar import Rule
from .lexer import BasicLexer, ContextualLexer, Lexer, LexerThread
from .lr_analysis import ParseTable
from .lr_parser import LRParser


class ParsingFrontend:
    """Connects a lexer to the LR parser.

    ``lexer_type`` is either 'basic' or 'contextual'.  The contextual lexer only matches the
    terminals that are acceptable in the current state of the parser.
    """

    def __init__(self, lexer_conf: LexerConf, parse_table: ParseTable, callbacks: Dict[Rule, Callable],
                 lexer_type: str = 'contextual') -> None:
        self.lexer_conf = lexer_conf
        self.parser = LRParser(parse_table, callbacks)
        self.lexer: Lexer

        if lexer_type == 'basic':
            self.lexer = BasicLexer(lexer_conf)
        elif lexer_type == 'contextual':
            states: Dict[int, Collection[str]] = {i: list(actions) for i, actions in enumerate(parse_table.states)}
            self.lexer = ContextualLexer(lexer_conf, states)
        else:
            raise ConfigurationError("Unknown lexer %r, expected 'basic' or 'contextual'" % (lexer_type,))

    def parse(self, text: str) -> Any:
        try:
            return self.parser.parse(LexerThread.from_text(self.lexer, text))
        except UnexpectedInput as e:
            if e._terminals_by_name is None:
                e._terminals_by_name = self.lexer_conf.terminals_by_name
            raise
