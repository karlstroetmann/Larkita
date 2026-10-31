"""Pygments lexers for Larkita grammars.

Larkita registers these lexers as Pygments plugins with the names 'larkita' and 'python-larkita', so they can be
used as in `pygmentize -l larkita grammar.g` or, in Jupyter, `display(Code(text, language='larkita'))`.
Pygments is not a requirement of Larkita; this module is only imported when Pygments looks for its lexers.

The lecture notes and the tutorial use copies of these classes with minted (larkita_lexer.py), since the
Pygments of TeX Live cannot load plugins.  Keep the classes identical.
"""
from pygments.lexer import RegexLexer, bygroups, inherit, using
from pygments.lexers.python import PythonLexer
from pygments.token import Comment, Keyword, Name, Number, Operator, Punctuation, String, Whitespace


class LarkitaLexer(RegexLexer):
    """A grammar for Larkita.  If the grammar is followed by the end of a Python string, the rest is Python."""
    name = 'Larkita'
    aliases = ['larkita']
    filenames = ['*.lark', '*.g']

    tokens = {
        'root': [
            # the rule or terminal that is defined in this line
            (r'^([ \t]*)([?!]?_?[a-z][a-z_0-9]*)(\.\d+)?([ \t]*)(:)',
             bygroups(Whitespace, Name.Function, Number, Whitespace, Punctuation)),
            (r'^([ \t]*)(_?[A-Z][A-Z_0-9]*)(\.\d+)?([ \t]*)(:)',
             bygroups(Whitespace, Name.Variable, Number, Whitespace, Punctuation)),
            # line breaks are separate tokens, so that the rules above see the beginning of every line
            (r'\n', Whitespace),
            (r'[ \t]+', Whitespace),
            (r'(""")((?:.|\n)*)', bygroups(String.Double, using(PythonLexer))),
            (r'//[^\n]*', Comment.Single),
            (r'%(ignore|import|declare|override|extend)\b', Keyword.Namespace),
            (r'(->)([ \t]*)(_?[a-zA-Z][a-zA-Z_0-9]*|"[^"\n]*")', bygroups(Operator, Whitespace, Name.Label)),
            (r'"(\\.|[^"\\\n])*"i?', String),
            (r'/(?!/)(\\/|\\\\|[^/\n])*?/[imslux]*', String.Regex),
            (r'_?[A-Z][A-Z_0-9]*', Name.Variable),
            (r'_?[a-z][a-z_0-9]*', Name),
            (r'\d+', Number),
            (r'[|*+?~]|\.\.', Operator),
            (r'[()\[\]:,.]', Punctuation),
        ],
    }


class PythonLarkitaLexer(PythonLexer):
    """Python code in which the raw strings r\"\"\"...\"\"\" are Larkita grammars.  The string may be unfinished."""
    name = 'Python with Larkita grammars'
    aliases = ['python-larkita']

    tokens = {
        'root': [
            (r'(r)(""")((?:.|\n)*?)("""|\Z)',
             bygroups(String.Affix, String.Double, using(LarkitaLexer), String.Double)),
            inherit,
        ],
    }
