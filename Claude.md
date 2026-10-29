I want to create a more light-weight version of the Python parser generator Lark.
I will name it Larkita.

It should satisfy the following specification:

* It should always produce a canonical LR(1) parser, not an LALR parser.
  The fact that this might increase the size of the parse tables does not bother me.

* The generated parser should return an abstract syntax tree that is represented
  not as an object of a class, but rather as a nested tuple.  I will specify how this works
  via some examples.

  (a) The grammar rule

        stmnt: IDENTIFIER ":=" expr ";"

      should return an abstract syntax tree of the form

        ((":=", ";"), ("IDENTIFIER", name), ast(expr))

      where ast(expr) is the abstract syntax tree returned when parsing expr
      and name is the string recognized as IDENTIFIER.

  (b) The grammar rule

        stmnt: expr ";"

      should return an abstract syntax tree of the form

        (";", ast(expr))

      where ast(expr) is the abstract syntax tree returned when parsing expr.

  (c) The grammar rule

        expr: expr "+" product

      should return an abstract syntax tree of the form

        ("+", ast(expr), ast(product))

      where ast(expr) is the abstract syntax tree returned when parsing expr.

  (d) The grammar rule

        factor: "(" expr ")"    %ignore "(", ")"

      should return the abstract syntax tree

        ast(expr)

      where ast(expr) is the abstract syntax tree returned when parsing expr because the
      tokens "(" and ")" are ignored for this rule.

  (e) In general, if we have a grammar rule of the form

        a: X1 X2 ... Xn

      then in order to decide the form of the abstract syntax tree that is returned we have to check
      which of the Xi are literal tokens that are enclosed in double quotes and that are not ignored.
      Then the tuple that is returned starts with a tuple of all those literal tokens.  If there is
      just one such token, the tuple starts with this token.  After that, the abstract syntax trees
      of the remaining variables and tokens are appended to the tuple.

  (f) The grammar rule

        atom: IDENTIFIER "(" expr_list ")" -> "call"

      should return the abstract syntax tree

        ("call", ast(IDENTIFIER), ast(expr_list))

  (g) The grammar rule

        atom: IDENTIFIER

      should return the abstract syntax tree

        ("IDENTIFIER", name)

      where name is the string that has been recognized as the token IDENTIFIER.

  (h) The grammar rule

        expr_list: (expr ("," expr)*)

      should return the abstract syntax tree

        (",", ast(expr_1), ast(expr_2), ..., ast(expr_n))

      where ast(expr_i) is the abstract syntax tree of the ith expression.

  (i) The grammar rule

        set_expr: "{" expr ("," expr)* "}"

      should return the abstract syntax tree

        (("{", ",", "}"), ast(expr_1), ast(expr_2), ..., ast(expr_n))

      where ast(expr_i) is the abstract syntax tree of the ith expression.

The directory `new-syntax` contains two example grammars that exhibit the new syntax.

In order to be debuggable the parser generator should always create an output file
that contains all LR states where every grammar rule is annotated with all the follow tokens.

## Clarifications

The following points make the rules above precise.

1.  **Head.**  The literal tokens at the front of the tuple are called the *head*.
    The head of an alternative is determined *statically* from the alternative as
    it is written in the grammar, not from the tokens that are actually read.
    Hence `f(a)` with rule (h) yields `("call", ("IDENTIFIER", "f"), (",", ast(a)))`.
    The literals are listed in textual order, one entry per occurrence, so
    `"for" "(" assignment ";" expr ";" assignment ")" statement` has the head
    `("for", "(", ";", ";", ")")`.  Literals inside repetitions, optional parts
    and nested groups belong to the head as well.

2.  **Pass-through.**  If an alternative has no head (all its literals are ignored
    or there are none), consists of exactly one symbol, contains no `*`, `+`, `?`,
    `[...]` or `|` operators, and has no alias, then it returns the abstract syntax
    tree of that symbol unchanged.  Examples: (d), (g), and `expr: product`.
    This is decided statically, so `program: statement*` never passes through,
    not even when the input contains exactly one statement.

3.  **Rule name as head.**  If an alternative has no head and is not a pass-through,
    the name of the rule is used as head.  For example, `program: statement*`
    yields `("program", ast(s_1), ..., ast(s_n))`, and `set_expr: "{" "}"` with
    the braces ignored yields `("set_expr",)`.

4.  **Flattening.**  Groups and repetitions are flattened into the tuple of the
    alternative they occur in, as in (h) and (i).

5.  **Optional parts.**  An optional part (`[...]` or `?`) that is absent is simply
    left out of the tuple; there is no `None` placeholder.

6.  **Named tokens.**  A named token always becomes `(NAME, text)`.  The text is
    never converted, so `NUMBER` yields `("NUMBER", "42")`.  Inline regular
    expressions `/.../` in a rule are treated like named tokens.

7.  **Aliases.**  An alias replaces the whole head.  `-> "call"` and `-> call`
    mean the same.

8.  **The three forms of `%ignore`.**
    * `%ignore WS` (a named terminal on its own line): the lexer skips the token.
    * `%ignore "(", ")"` written after an alternative: these literals are dropped
      from the abstract syntax tree of *that alternative*.
    * `%ignore: "(", ")", "{", "}"` (with a colon) on its own line: these literals
      are dropped from the abstract syntax trees of *all* rules.

9.  **Conflicts.**  Shift/reduce conflicts are resolved in favour of shift and
    reported as a warning.  Reduce/reduce conflicts are errors (unless the rules
    have different priorities).  All conflicts are listed in the output file.

10. **Output file.**  If the grammar is read from a file, the output file has the
    same name with the extension `.out` and lives in the same directory
    (`expr.g` produces `expr.out`).  If the grammar is given as a string, the
    file is `grammar.out` in the current directory.  For every state it lists
    all items (kernel and closure) in the form `A → α • β  { lookaheads }`,
    followed by the actions, the gotos and the conflicts of that state.

11. **Start symbol.**  The start symbol is the first rule of the grammar, unless
    another start symbol is given explicitly.

## Scope

* The package is called `larkita`; `Larkita(grammar).parse(text)` returns a tuple.
* Kept from Lark: the grammar loader (including `%import` and `common.lark`),
  terminal definitions and priorities, and the basic and contextual lexers.
* Removed from Lark: the Earley, CYK and LALR parsers, the public
  Tree/Transformer/Visitor API, the reconstructor, tree templates, the standalone
  and nearley tools, the interactive parser, the cache, and Lark's tree-shaping
  features (`?rule`, `!rule`, `_rule`, `_TERMINAL`, placeholders for missing optionals).
  Also removed: grammar templates (`rule{x}: ...`), post-lexers (and the `Indenter`),
  lexer callbacks, `scan()`, and serialization.
* Lark's test suite is replaced by new tests (`python3 -m tests`).

## Code map

* `larkita/larkita.py`: the class `Larkita` (entry point).
* `larkita/load_grammar.py`: grammar loader; `_make_ast_spec` computes the head of an alternative.
* `larkita/lr_analysis.py`: canonical LR(1) automaton, parse table, conflict resolution.
* `larkita/ast_builder.py`: the reduction callbacks that build the nested tuples.
* `larkita/report.py`: writes the output file.
* `larkita/lr_parser.py`, `larkita/lexer.py`, `larkita/parser_frontends.py`: the runtime.
* `larkita/tree.py`, `larkita/visitors.py`, `larkita/parse_tree_builder.py`: internal, used to
  parse grammar files only.
