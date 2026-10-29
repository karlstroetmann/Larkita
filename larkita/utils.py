import unicodedata
import sys, re
import logging
from collections import deque
from dataclasses import dataclass
from typing import (Callable, Iterator, List, Optional, Tuple, TypeVar, Union, Dict, Any, Sequence, Iterable,
                    AbstractSet, Generic, AnyStr)

logger: logging.Logger = logging.getLogger("larkita")
logger.addHandler(logging.StreamHandler())
# Set to highest level, since we have some warnings amongst the code
# By default, we should not output any log messages
logger.setLevel(logging.CRITICAL)


T = TypeVar("T")


def classify(seq: Iterable, key: Optional[Callable] = None, value: Optional[Callable] = None) -> Dict:
    d: Dict[Any, Any] = {}
    for item in seq:
        k = key(item) if (key is not None) else item
        v = value(item) if (value is not None) else item
        try:
            d[k].append(v)
        except KeyError:
            d[k] = [v]
    return d


try:
    import regex    # type: ignore
    _has_regex = True
except ImportError:
    _has_regex = False

if sys.version_info >= (3, 11):
    import re._parser as sre_parse
    import re._constants as sre_constants
else:
    import sre_parse
    import sre_constants

categ_pattern = re.compile(r'\\p{[A-Za-z_]+}')

def get_regexp_width(expr: str) -> Union[Tuple[int, int], List[int]]:
    if _has_regex:
        # Since `sre_parse` cannot deal with Unicode categories of the form `\p{Mn}`, we replace these with
        # a simple letter, which makes no difference as we are only trying to get the possible lengths of the regex
        # match here below.
        regexp_final = re.sub(categ_pattern, 'A', expr)
    else:
        if re.search(categ_pattern, expr):
            raise ImportError('`regex` module must be installed in order to use Unicode categories.', expr)
        regexp_final = expr
    try:
        return [int(x) for x in sre_parse.parse(regexp_final).getwidth()]
    except sre_constants.error:
        if not _has_regex:
            raise ValueError(expr)
        else:
            # sre_parse does not support the new features in regex. To not completely fail in that case,
            # we manually test for the most important info (whether the empty string is matched)
            c = regex.compile(regexp_final)
            MAXWIDTH = getattr(sre_parse, "MAXWIDTH", sre_constants.MAXREPEAT)
            if c.match('') is None:
                return 1, int(MAXWIDTH)
            else:
                return 0, int(MAXWIDTH)


@dataclass(frozen=True)
class TextSlice(Generic[AnyStr]):
    """A view of a string, between the start and end indices. Never creates a copy."""
    text: AnyStr
    start: int
    end: int

    def __post_init__(self):
        if not isinstance(self.text, (str, bytes)):
            raise TypeError("text must be str or bytes")

        if self.start < 0:
            object.__setattr__(self, 'start', self.start + len(self.text))
            assert self.start >=0

        if self.end is None:
            object.__setattr__(self, 'end', len(self.text))
        elif self.end < 0:
            object.__setattr__(self, 'end', self.end + len(self.text))
            assert self.end <= len(self.text)

    @classmethod
    def cast_from(cls, text: 'TextOrSlice') -> 'TextSlice[AnyStr]':
        if isinstance(text, TextSlice):
            return text

        return cls(text, 0, len(text))

    def __len__(self):
        return self.end - self.start


TextOrSlice = Union[AnyStr, 'TextSlice[AnyStr]']


_ID_START =    'Lu', 'Ll', 'Lt', 'Lm', 'Lo', 'Mn', 'Mc', 'Pc'
_ID_CONTINUE = _ID_START + ('Nd', 'Nl',)

def _test_unicode_category(s: str, categories: Sequence[str]) -> bool:
    if len(s) != 1:
        return all(_test_unicode_category(char, categories) for char in s)
    return s == '_' or unicodedata.category(s) in categories

def is_id_continue(s: str) -> bool:
    """
    Checks if all characters in `s` are alphanumeric characters (Unicode standard, so diacritics, indian vowels, non-latin
    numbers, etc. all pass). Synonymous with a Python `ID_CONTINUE` identifier. See PEP 3131 for details.
    """
    return _test_unicode_category(s, _ID_CONTINUE)

def is_id_start(s: str) -> bool:
    """
    Checks if all characters in `s` are alphabetic characters (Unicode standard, so diacritics, indian vowels, non-latin
    numbers, etc. all pass). Synonymous with a Python `ID_START` identifier. See PEP 3131 for details.
    """
    return _test_unicode_category(s, _ID_START)


def dedup_list(l: Iterable[T]) -> List[T]:
    """Given a list (l) will removing duplicates from the list,
       preserving the original order of the list. Assumes that
       the list entries are hashable."""
    return list(dict.fromkeys(l))


def classify_bool(seq: Iterable, pred: Callable) -> Any:
    false_elems = []
    true_elems = [elem for elem in seq if pred(elem) or false_elems.append(elem)]  # type: ignore[func-returns-value]
    return true_elems, false_elems


def bfs(initial: Iterable, expand: Callable) -> Iterator:
    open_q = deque(list(initial))
    visited = set(open_q)
    while open_q:
        node = open_q.popleft()
        yield node
        for next_node in expand(node):
            if next_node not in visited:
                visited.add(next_node)
                open_q.append(next_node)


def small_factors(n: int, max_factor: int) -> List[Tuple[int, int]]:
    """
    Splits n up into smaller factors and summands <= max_factor.
    Returns a list of [(a, b), ...]
    so that the following code returns n:

    n = 1
    for a, b in values:
        n = n * a + b

    Currently, we also keep a + b <= max_factor, but that might change
    """
    assert n >= 0
    assert max_factor > 2
    if n <= max_factor:
        return [(n, 0)]

    for a in range(max_factor, 1, -1):
        r, b = divmod(n, a)
        if a + b <= max_factor:
            return small_factors(r, max_factor) + [(a, b)]
    assert False, "Failed to factorize %s" % n


class OrderedSet(AbstractSet[T]):
    """A minimal OrderedSet implementation, using a dictionary.

    (relies on the dictionary being ordered)
    """
    def __init__(self, items: Iterable[T] =()):
        self.d = dict.fromkeys(items)

    def __contains__(self, item: Any) -> bool:
        return item in self.d

    def add(self, item: T):
        self.d[item] = None

    def __iter__(self) -> Iterator[T]:
        return iter(self.d)

    def remove(self, item: T):
        del self.d[item]

    def __bool__(self):
        return bool(self.d)

    def __len__(self) -> int:
        return len(self.d)

    def __repr__(self):
        return f"{type(self).__name__}({', '.join(map(repr,self))})"
