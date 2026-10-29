"""Transformers and visitors for the internal tree class.  They are used by the grammar loader."""

from functools import update_wrapper
from inspect import getmembers, getmro
from typing import Callable, List

from .tree import Tree
from .exceptions import VisitError, GrammarError
from .lexer import Token


class _DiscardType:
    """When the Discard value is returned from a transformer callback,
    that node is discarded and won't appear in the parent."""

    def __repr__(self):
        return "larkita.visitors.Discard"

Discard = _DiscardType()


class _Decoratable:
    "Provides support for decorating methods with @inline_args"

    @classmethod
    def _apply_inline_args(cls):
        mro = getmro(cls)
        assert mro[0] is cls
        libmembers = {name for _cls in mro[1:] for name, _ in getmembers(_cls)}
        for name, value in getmembers(cls):

            # Make sure the function isn't inherited (unless it's overwritten)
            if name.startswith('_') or (name in libmembers and name not in cls.__dict__):
                continue
            if not callable(value):
                continue

            # Skip if inline_args was already applied (at the function level)
            if isinstance(cls.__dict__[name], _InlineArgsWrapper):
                continue

            setattr(cls, name, _InlineArgsWrapper(cls.__dict__[name]))
        return cls


class Transformer(_Decoratable):
    """Transformers work bottom-up, starting with visiting the leaves and working
    their way up until ending at the root of the tree.

    For each node visited, the transformer calls the method named after the node's ``data``
    and uses the returned value to replace the node.  If there is no such method, it calls
    ``__default__``, which by default creates a copy of the node.
    """
    __visit_tokens__ = True

    def __init__(self,  visit_tokens: bool=True) -> None:
        self.__visit_tokens__ = visit_tokens

    def _call_userfunc(self, tree, new_children=None):
        # Assumes tree is already transformed
        children = new_children if new_children is not None else tree.children
        try:
            f = getattr(self, tree.data)
        except AttributeError:
            return self.__default__(tree.data, children)
        else:
            try:
                if isinstance(f, _InlineArgsWrapper):
                    return f(*children)
                else:
                    return f(children)
            except GrammarError:
                raise
            except Exception as e:
                raise VisitError(tree.data, tree, e)

    def _call_userfunc_token(self, token):
        try:
            f = getattr(self, token.type)
        except AttributeError:
            return self.__default_token__(token)
        else:
            try:
                return f(token)
            except GrammarError:
                raise
            except Exception as e:
                raise VisitError(token.type, token, e)

    def _transform_children(self, children):
        for c in children:
            if isinstance(c, Tree):
                res = self._transform_tree(c)
            elif self.__visit_tokens__ and isinstance(c, Token):
                res = self._call_userfunc_token(c)
            else:
                res = c

            if res is not Discard:
                yield res

    def _transform_tree(self, tree):
        children = list(self._transform_children(tree.children))
        return self._call_userfunc(tree, children)

    def transform(self, tree):
        "Transform the given tree, and return the final result"
        res = list(self._transform_children([tree]))
        if not res:
            return None
        assert len(res) == 1
        return res[0]

    def __mul__(self, other):
        """Chain two transformers together, returning a new transformer."""
        return TransformerChain(self, other)

    def __default__(self, data, children):
        """Default function that is called if there is no attribute matching ``data``"""
        return Tree(data, children)

    def __default_token__(self, token):
        """Default function that is called if there is no attribute matching ``token.type``"""
        return token


class TransformerChain:

    def __init__(self, *transformers) -> None:
        self.transformers = transformers

    def transform(self, tree):
        for t in self.transformers:
            tree = t.transform(tree)
        return tree

    def __mul__(self, other):
        return TransformerChain(*self.transformers + (other,))


class Transformer_InPlace(Transformer):
    """Same as Transformer, but non-recursive, and changes the tree in-place instead of returning new instances"""
    def _transform_tree(self, tree):           # Cancel recursion
        return self._call_userfunc(tree)

    def transform(self, tree):
        for subtree in tree.iter_subtrees():
            subtree.children = list(self._transform_children(subtree.children))

        return self._transform_tree(tree)


class Transformer_NonRecursive(Transformer):
    """Same as Transformer but non-recursive.  Like Transformer, it doesn't change the original tree."""

    def transform(self, tree):
        # Tree to postfix
        rev_postfix = []
        q: List = [tree]
        while q:
            t = q.pop()
            rev_postfix.append(t)
            if isinstance(t, Tree):
                q += t.children

        # Postfix to tree
        stack: List = []
        for x in reversed(rev_postfix):
            if isinstance(x, Tree):
                size = len(x.children)
                if size:
                    # Discarded children are kept on the stack as placeholders, so
                    # that this slice stays aligned with x.children. Drop them here.
                    args = [a for a in stack[-size:] if a is not Discard]
                    del stack[-size:]
                else:
                    args = []

                stack.append(self._call_userfunc(x, args))    # may be Discard

            elif self.__visit_tokens__ and isinstance(x, Token):
                stack.append(self._call_userfunc_token(x))    # may be Discard
            else:
                stack.append(x)

        result, = stack  # We should have only one tree remaining
        if result is Discard:  # the whole tree was discarded
            return None
        return result


class Visitor:
    """Tree visitor, non-recursive.  Visiting a node calls the method named after ``tree.data``."""

    def _call_userfunc(self, tree):
        return getattr(self, tree.data, self.__default__)(tree)

    def __default__(self, tree):
        return tree

    def visit(self, tree: Tree) -> Tree:
        "Visits the tree, starting with the leaves and finally the root (bottom-up)"
        for subtree in tree.iter_subtrees():
            self._call_userfunc(subtree)
        return tree

    def visit_topdown(self, tree: Tree) -> Tree:
        "Visit the tree, starting at the root, and ending at the leaves (top-down)"
        for subtree in tree.iter_subtrees_topdown():
            self._call_userfunc(subtree)
        return tree


class _InlineArgsWrapper:
    """Wraps a transformer method so that it receives the children as separate arguments."""
    base_func: Callable

    def __init__(self, func: Callable):
        if isinstance(func, _InlineArgsWrapper):
            func = func.base_func
        self.base_func = func
        update_wrapper(self, func)

    def __call__(self, *args, **kwargs):
        return self.base_func(*args, **kwargs)

    def __get__(self, instance, owner=None):
        try:
            # Use the __get__ attribute of the type instead of the instance
            # to fully mirror the behavior of getattr
            g = type(self.base_func).__get__
        except AttributeError:
            return self
        else:
            return _InlineArgsWrapper(g(self.base_func, instance, owner))


def inline_args(obj):
    """Decorator for a transformer class or method: the children are passed as ``*args`` instead of a list."""
    try:
        _apply = obj._apply_inline_args
    except AttributeError:
        return _InlineArgsWrapper(obj)
    else:
        return _apply()
