from copy import deepcopy
from types import ModuleType
from typing import Collection, Dict

from .lexer import TerminalDef


class LexerConf:
    terminals: Collection[TerminalDef]
    terminals_by_name: Dict[str, TerminalDef]
    re_module: ModuleType
    ignore: Collection[str]
    g_regex_flags: int
    skip_validation: bool

    def __init__(self, terminals: Collection[TerminalDef], re_module: ModuleType, ignore: Collection[str]=(),
                 g_regex_flags: int=0, skip_validation: bool=False):
        self.terminals = terminals
        self.terminals_by_name = {t.name: t for t in self.terminals}
        assert len(self.terminals) == len(self.terminals_by_name)
        self.ignore = ignore
        self.g_regex_flags = g_regex_flags
        self.re_module = re_module
        self.skip_validation = skip_validation

    def __deepcopy__(self, memo=None):
        return type(self)(
            deepcopy(self.terminals, memo),
            self.re_module,
            deepcopy(self.ignore, memo),
            deepcopy(self.g_regex_flags, memo),
            deepcopy(self.skip_validation, memo),
        )
