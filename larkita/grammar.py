from typing import Optional, Tuple, ClassVar, Sequence, Union

TOKEN_DEFAULT_PRIORITY = 0


class Symbol:
    __slots__ = ('name',)

    name: str
    is_term: ClassVar[bool] = NotImplemented

    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other):
        if not isinstance(other, Symbol):
            return NotImplemented
        return self.is_term == other.is_term and self.name == other.name

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return '%s(%r)' % (type(self).__name__, self.name)

    fullrepr = property(__repr__)

    def renamed(self, f):
        return type(self)(f(self.name))


class Terminal(Symbol):
    """A terminal in a rule.  ``filter_out`` is true if it was written as a string literal,
    so that it becomes part of the head instead of a child of the abstract syntax tree.
    A string literal inside an inner alternative that could not be expanded (see
    ``load_grammar._expand_alternatives``) is a child instead; then ``text`` is the literal."""
    __slots__ = ('filter_out', 'text')

    is_term: ClassVar[bool] = True

    text: Optional[str]

    def __init__(self, name: str, filter_out: bool = False, text: Optional[str] = None) -> None:
        self.name = name
        self.filter_out = filter_out
        self.text = text

    @property
    def fullrepr(self):
        return '%s(%r, %r, %r)' % (type(self).__name__, self.name, self.filter_out, self.text)

    def renamed(self, f):
        return type(self)(f(self.name), self.filter_out, self.text)


class NonTerminal(Symbol):
    __slots__ = ()

    is_term: ClassVar[bool] = False


class RuleOptions:
    """``expand1`` is only used by the internal parser for grammar files (the ``?rule`` of Lark)."""
    __slots__ = ('expand1', 'priority')

    expand1: bool
    priority: Optional[int]

    def __init__(self, expand1: bool=False, priority: Optional[int]=None) -> None:
        self.expand1 = expand1
        self.priority = priority

    def __repr__(self):
        return 'RuleOptions(%r, %r)' % (self.expand1, self.priority)


Head = Union[str, Tuple[str, ...]]


class AstSpec:
    """Describes how the abstract syntax tree of a grammar alternative is built.

    If ``head`` is None, the alternative passes the abstract syntax tree of its only child through.
    Otherwise the abstract syntax tree is the tuple ``(head, child_1, ..., child_n)``.
    """
    __slots__ = ('head',)

    head: Optional[Head]

    def __init__(self, head: Optional[Head]) -> None:
        self.head = head

    @property
    def passthrough(self) -> bool:
        return self.head is None

    def __repr__(self):
        return 'AstSpec(%r)' % (self.head,)


class Rule:
    """
        origin : a symbol
        expansion : a list of symbols
        order : index of this expansion amongst all rules of the same name
        ast : how the abstract syntax tree is built, or None for the auxiliary rules that are
              created for EBNF repetitions (their children are spliced into the parent's tuple)
    """
    __slots__ = ('origin', 'expansion', 'options', 'order', 'ast', '_hash')

    origin: NonTerminal
    expansion: Sequence[Symbol]
    order: int
    options: RuleOptions
    ast: Optional[AstSpec]
    _hash: int

    def __init__(self, origin: NonTerminal, expansion: Sequence[Symbol],
                 order: int=0, options: Optional[RuleOptions]=None, ast: Optional[AstSpec]=None):
        self.origin = origin
        self.expansion = expansion
        self.order = order
        self.options = options or RuleOptions()
        self.ast = ast
        self._hash = hash((self.origin, tuple(self.expansion)))

    def __str__(self):
        return '<%s : %s>' % (self.origin.name, ' '.join(x.name for x in self.expansion))

    def __repr__(self):
        return 'Rule(%r, %r, %r, %r)' % (self.origin, self.expansion, self.options, self.ast)

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        if not isinstance(other, Rule):
            return False
        return self.origin == other.origin and self.expansion == other.expansion
