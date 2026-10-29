import os
import re
import warnings
from typing import Any, Callable, IO, List, Optional, Sequence, Union

from .ast_builder import create_callbacks
from .common import LexerConf
from .exceptions import ConflictWarning, GrammarError, assert_config
from .grammar import Rule
from .lexer import TerminalDef
from .load_grammar import load_grammar
from .lr_analysis import LR1Analyzer, Conflict, ParseTable
from .parser_frontends import ParsingFrontend
from .report import write_report


class Larkita:
    """A parser generator for canonical LR(1) parsers that return abstract syntax trees as nested tuples.

    Parameters:
        grammar: the grammar, either as a string or as an open file.
        start: the start symbol.  Defaults to the first rule of the grammar.
        lexer: 'contextual' (the default) only matches the terminals that are acceptable in the
            current state of the parser; 'basic' always matches all terminals.
        import_paths: additional places to search for the grammars named by ``%import``.
        source_path: the file name of the grammar.  It is used for relative imports and
            to name the output file.
        out_file: the file that receives the description of the LR(1) automaton.  It defaults
            to ``source_path`` with the extension ``.out``, or to ``grammar.out`` in the current
            directory if the grammar is neither read from a file nor given a ``source_path``.
        regex: use the ``regex`` module instead of ``re``.
        g_regex_flags: flags that are applied to all terminals.

    The output file is always written, even if the grammar has unresolved conflicts.  In that case
    a GrammarError is raised afterwards.  Shift/reduce conflicts are resolved in favour of shift and
    reported with a ConflictWarning.
    """

    source_path: Optional[str]
    out_file: str
    start: str
    terminals: List[TerminalDef]
    rules: List[Rule]
    ignore_tokens: List[str]
    parse_table: ParseTable
    conflicts: List[Conflict]

    def __init__(self, grammar: Union[str, IO[str]], *, start: Optional[str] = None, lexer: str = 'contextual',
                 import_paths: Sequence[Union[str, Callable]] = (), source_path: Optional[str] = None,
                 out_file: Optional[str] = None, regex: bool = False, g_regex_flags: int = 0) -> None:
        if not isinstance(grammar, str):
            if source_path is None:
                source_path = getattr(grammar, 'name', None)
            grammar = grammar.read()
        assert_config(lexer, ('contextual', 'basic'))

        if regex:
            try:
                import regex as re_module   # type: ignore
            except ImportError:
                raise ImportError('`regex` module must be installed if calling `Larkita(regex=True)`.')
        else:
            re_module = re

        self.source_path = source_path
        source = source_path or '<string>'
        self.grammar, self.used_files = load_grammar(grammar, source, list(import_paths))

        start = start or self.grammar.first_rule
        if start is None:
            raise GrammarError("The grammar does not contain any rules")
        self.start = start

        self.terminals, self.rules, self.ignore_tokens = self.grammar.compile([start], ())

        if out_file is None:
            out_file = os.path.splitext(source_path)[0] + '.out' if source_path else 'grammar.out'
        self.out_file = out_file

        analyzer = LR1Analyzer(self.rules, start)
        self.parse_table = analyzer.parse_table
        self.conflicts = analyzer.conflicts
        terminal_names = {t.name: t.user_repr() for t in self.terminals}
        write_report(out_file, analyzer, terminal_names, source)

        unresolved = [c for c in self.conflicts if not c.resolved]
        if unresolved:
            raise GrammarError("The grammar has %d unresolved reduce/reduce conflict(s), see %s:\n%s"
                               % (len(unresolved), out_file,
                                  '\n'.join('  * state %d on %s' % (c.state, terminal_names.get(c.terminal, c.terminal))
                                            for c in unresolved)))
        shift_reduce = [c for c in self.conflicts if c.shift_state is not None]
        if shift_reduce:
            warnings.warn("%d shift/reduce conflict(s) were resolved as shift, see %s" % (len(shift_reduce), out_file),
                          ConflictWarning, stacklevel=2)

        lexer_conf = LexerConf(self.terminals, re_module, self.ignore_tokens, g_regex_flags)
        self.parser = ParsingFrontend(lexer_conf, self.parse_table, create_callbacks(self.rules), lexer)

    @classmethod
    def open(cls, grammar_filename: str, rel_to: Optional[str] = None, **options) -> 'Larkita':
        """Creates an instance of Larkita with the grammar given by its filename.

        If ``rel_to`` is provided, the function will find the grammar filename in relation to it.

        Example:

            >>> Larkita.open("grammar_file.g", rel_to=__file__)
            Larkita(...)
        """
        if rel_to:
            basepath = os.path.dirname(rel_to)
            grammar_filename = os.path.join(basepath, grammar_filename)
        with open(grammar_filename, encoding='utf8') as f:
            return cls(f, **options)

    def __repr__(self):
        return 'Larkita(open(%r), start=%r)' % (self.source_path or '<string>', self.start)

    def parse(self, text: str) -> Any:
        """Parses the text and returns its abstract syntax tree (a nested tuple).

        Raises UnexpectedCharacters or UnexpectedToken if the text does not match the grammar.
        """
        return self.parser.parse(text)
