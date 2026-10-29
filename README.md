# Larkita

Larkita is a light-weight version of the Python parser generator
[Lark](https://github.com/lark-parser/lark).  It differs from Lark in three ways:

* It always generates a **canonical LR(1) parser** (not LALR, Earley or CYK).
* The parser returns the **abstract syntax tree as a nested tuple**, not as a tree
  of objects.  How the tuple is built follows from the grammar itself; you never
  have to write tree-building code.
* Every time a parser is generated, Larkita writes an **output file** with all
  the LR(1) states, every item annotated with its lookahead tokens.  This makes
  conflicts easy to debug.

Grammars are written in Lark's EBNF notation, with a few additions for building
the abstract syntax tree.

## Installation

Larkita needs Python 3.8 or newer and has no dependencies.  The source code is
on GitHub at <https://github.com/karlstroetmann/Larkita>.  To install it, run

    git clone https://github.com/karlstroetmann/Larkita.git
    cd Larkita
    pip install .

or simply put the directory `larkita` on your `PYTHONPATH`.  You can also install
Larkita directly from GitHub:

    pip install git+https://github.com/karlstroetmann/Larkita.git

If the optional package `interegular` is installed, Larkita checks whether the
regular expressions of different terminals can match the same text.  It reports
such collisions via `larkita.logger`, which is silent by default; call
`larkita.logger.setLevel(logging.WARNING)` to see them.

## Quick start

```python
from larkita import Larkita

grammar = r'''
stmnt: IDENTIFIER ":=" expr ";"
     | expr ";"

expr: expr "+" product
    | expr "-" product
    | product

product: product "*" factor
       | product "/" factor
       | factor

factor: "(" expr ")"    %ignore "(", ")"
      | NUMBER
      | IDENTIFIER

%import common.CNAME -> IDENTIFIER
%import common.NUMBER
%import common.WS
%ignore WS
'''

parser = Larkita(grammar)
print(parser.parse('x := (a + 3) * b;'))
```

prints

```python
((':=', ';'), ('IDENTIFIER', 'x'), ('*', ('+', ('IDENTIFIER', 'a'), ('NUMBER', '3')), ('IDENTIFIER', 'b')))
```

and writes the description of the automaton to `grammar.out`.  To read the
grammar from a file, use

```python
parser = Larkita.open('new-syntax/expr.g')     # writes new-syntax/expr.out
```

The start symbol is the first rule of the grammar (here `stmnt`).

## How the abstract syntax tree is built

Consider an alternative `a: X1 X2 ... Xn`.  The literal tokens written in double
quotes form the **head** of the tuple; all other symbols become its **children**:

    (head, ast(child_1), ..., ast(child_k))

| Grammar | Abstract syntax tree |
|---|---|
| `expr: expr "+" product` | `("+", ast(expr), ast(product))` |
| `stmnt: expr ";"` | `(";", ast(expr))` |
| `stmnt: IDENTIFIER ":=" expr ";"` | `((":=", ";"), ("IDENTIFIER", name), ast(expr))` |
| `atom: IDENTIFIER` | `("IDENTIFIER", name)` |
| `expr: product` | `ast(product)` |
| `factor: "(" expr ")"  %ignore "(", ")"` | `ast(expr)` |
| `atom: IDENTIFIER "(" args ")" -> "call"` | `("call", ("IDENTIFIER", name), ast(args))` |
| `args: expr ("," expr)*` | `(",", ast(expr_1), ..., ast(expr_n))` |
| `set: "{" expr ("," expr)* "}"` | `(("{", ",", "}"), ast(expr_1), ..., ast(expr_n))` |
| `program: statement*` | `("program", ast(statement_1), ..., ast(statement_n))` |
| `stmnt: "return" [expr] ";"` | `(("return", ";"),)` or `(("return", ";"), ast(expr))` |

In detail:

* **Head.**  The head consists of all literals of the alternative that are not
  ignored, in the order in which they are written, one entry per occurrence.  If
  there is exactly one literal, the head is that string; otherwise it is a tuple
  of strings.  The head is fixed by the grammar, not by the input: `f(a)` with the
  rule for `args` above yields `(",", ast(a))`, even though no comma was read.
  Literals inside repetitions, optional parts and groups belong to the head, too.
* **Named tokens** become `(NAME, text)`, e.g. `("NUMBER", "42")`.  The text is
  not converted.  Inline regular expressions `/.../` are treated like named tokens.
* **Pass-through.**  If an alternative has no head and consists of exactly one
  symbol (with no `*`, `+`, `?`, `[...]` or `|`), it returns the abstract syntax
  tree of that symbol unchanged.
* **Rule name as head.**  If an alternative has no head and is not a pass-through,
  the name of the rule is used as head, e.g. `("program", ...)`.  An empty
  alternative yields `("rule_name",)`.
* **Repetitions and groups are flattened** into the tuple of the alternative.
* **Missing optional parts are left out**; there is no `None` placeholder.
* **Aliases** replace the whole head: `-> "call"` and `-> call` are equivalent.

### Ignoring literals

`%ignore` has three forms:

```
%ignore WS                      // the lexer skips the terminal WS
factor: "(" expr ")"  %ignore "(", ")"
                                // "(" and ")" are left out of the head of this alternative
%ignore: "(", ")", "{", "}"     // these literals are left out of the heads of all rules
```

With `%ignore: "(", ")"`, the rule
`statement: "while" "(" expr ")" statement` yields
`("while", ast(expr), ast(statement))`.

## Grammar syntax

Larkita reads Lark grammars:

* Rules have lowercase names, terminals have uppercase names.
* `|` separates alternatives, `( ... )` groups, `[ ... ]` and `?` mark optional
  parts, `*` and `+` repeat, and `~ n` or `~ n..m` repeat a fixed number of times.
* String literals are written as `"..."` (append `i` for case-insensitive
  matching), regular expressions as `/.../flags`.
* Terminals are defined with `NAME: ...`; `NAME.p: ...` gives a terminal the
  priority `p`, and `rule.p: ...` gives a rule the priority `p` (used to resolve
  reduce/reduce conflicts).
* `%import common.NUMBER` imports terminals from Lark's standard library
  (`larkita/grammars/common.lark`), and `%import .file.rule` imports from a
  grammar file next to the current one.  `-> NAME` renames an import.
* `%declare`, `%extend` and `%override` work as in Lark.
* `//` starts a comment.

Not supported (compared with Lark): the rule modifiers `?rule` and `!rule`,
templates, post-lexers (such as Lark's `Indenter`), lexer callbacks, and
transformers.  Rules and terminals whose names start with `_` are not inlined
or filtered.

## The output file

If the grammar is read from a file, the output file has the same name with the
extension `.out` (`expr.g` produces `expr.out`).  Otherwise it is `grammar.out` in
the current directory.  The parameter `out_file` sets another path.

The file contains

1. the rules after the EBNF operators have been expanded, each followed by the
   abstract syntax tree that a reduction produces, e.g.
   `(3) expr → expr "+" product  ⇒ ("+", ast(expr), ast(product))`;
2. a list of all conflicts and how they were resolved;
3. all states.  Each state lists its items with their lookahead tokens (closure
   items are marked with `+`), followed by its actions and gotos:

```
State 2

    (1)   stmnt → IDENTIFIER • ":=" expr ";"  { $END }
    (11)  factor → IDENTIFIER •               { "*", "+", "-", "/", ";" }

    ":="  shift and go to state 8
    "*"   reduce using rule (11) factor → IDENTIFIER
    "+"   reduce using rule (11) factor → IDENTIFIER
    "-"   reduce using rule (11) factor → IDENTIFIER
    "/"   reduce using rule (11) factor → IDENTIFIER
    ";"   reduce using rule (11) factor → IDENTIFIER
```

## Conflicts

* **Shift/reduce conflicts** are resolved in favour of shift (so the dangling
  `else` belongs to the innermost `if`).  Larkita issues a `ConflictWarning`.
* **Reduce/reduce conflicts** are resolved in favour of the rule with the highest
  priority.  If no rule has a higher priority than the others, `Larkita` raises a
  `GrammarError`; the output file is written anyway.

## API

```python
Larkita(grammar, *, start=None, lexer='contextual', import_paths=(),
        source_path=None, out_file=None, regex=False, g_regex_flags=0)
```

* `grammar`: the grammar as a string or an open file.
* `start`: the start symbol; defaults to the first rule.
* `lexer`: `'contextual'` (only matches the terminals that the parser can accept
  in its current state) or `'basic'`.
* `import_paths`: additional directories to search for imported grammars.
* `source_path`: the file name of the grammar, used for relative imports and to
  name the output file.
* `out_file`: the path of the output file.
* `regex`: use the `regex` module instead of `re`.
* `g_regex_flags`: flags applied to all terminals.

`Larkita.open(filename, rel_to=None, **options)` reads the grammar from a file.

`parser.parse(text)` returns the abstract syntax tree.  It raises
`UnexpectedCharacters` if the lexer cannot match the input, and `UnexpectedToken`
if the parser receives a token it cannot accept (at the end of the input, the
token has the type `$END`).  All exceptions derive from `LarkitaError`.

After construction, `parser.conflicts`, `parser.rules`, `parser.terminals`,
`parser.parse_table` and `parser.out_file` describe the generated parser.

## Examples and tests

The directory `new-syntax` contains two example grammars: `expr.g` (arithmetic
expressions) and `interpreter.g` (a small imperative language with sets).

Run the tests with

    python3 -m tests

## License

MIT.  Larkita is derived from [Lark](https://github.com/lark-parser/lark) by
Erez Shinan; see `LICENSE`.
