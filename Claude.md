I want to create a more light-weight version of the Python parser generator Lark.
I will name it Larkita.

It should satisfy the following specification:

* It should always produce a canonical LR(1) parser, not an LALR parser.
  The fact that this might increase the size of the parse tables does not bother me.

* The generated parser should return an abstract syntax tree that is represented
  not as an object of a class, but rather as a nested tuple.  I will specify how this works
  via some examples.

  (a) The grammar rule

        stmnt: IDENTIFIER ":=" expr ";";

      should return an abstract syntax tree of the form

        ((":=", ";"), ("IDENTIFIER", name), ast(expr))

      where ast(expr) is the abstract syntax tree returned when parsing expr
      and name is the string recognized as IDENTIFIER.

  (b) The grammar rule

        stmnt: expr ";";

      should return an abstract syntax tree of the form

        (";", ast(expr))

      where ast(expr) is the abstract syntax tree returned when parsing expr.

  (c) The grammar rule

        expr: expr "+" product;

      should return an abstract syntax tree of the form

        ("+", ast(expr), ast(product))

      where ast(expr) is the abstract syntax tree returned when parsing expr.

  (d) The grammar rule

        factor: "(" expr ")"    %ignore "(", ")";

      should return the abstract syntax tree

        ast(expr)

      where ast(expr) is the abstract syntax tree returned when parsing expr because the
      tokens "(" and ")" are ignored for this rule.

  (e) In general, if we have a grammar rule of the form

        a: X1 X2 ... Xn;

      then in order to decide the form of the abstract syntax tree that is returned we have to check
      which of the Xi are literal tokens that are enclosed in double quotes and that are not ignored.
      Then the tuple that is returned starts with a tuple of all those literal tokens.  If there is
      just one such token, the tuple starts with this token.  After that, the abstract syntax trees
      of the remaining variables and tokens are appended to the tuple.

  (f) The grammar rule

        atom: IDENTIFIER "(" expr_list ")" -> "call";

      should return the abstract syntax tree

        ("call", ast(IDENTIFIER), ast(expr_list))

  (g) The grammar rule

        atom: IDENTIFIER;

      should return the abstract syntax tree

        ("IDENTIFIER", name)

      where name is the string that has been recognized as the token IDENTIFIER.

  (h) The grammar rule

        expr_list: (expr ("," expr)*);

      should return the abstract syntax tree

        (",", ast(expr_1), ast(expr_2), ..., ast(expr_n))

      where ast(expr_i) is the abstract syntax tree of the ith expression.

  (i) The grammar rule

        set_expr: "{" expr ("," expr)* "}";

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
    and nested groups belong to the head as well, except for the literals of the
    inner alternatives described in 5.

2.  **Pass-through.**  If an alternative has no head (all its literals are ignored
    or there are none), consists of exactly one symbol, contains no `*`, `+`, `?`,
    `[...]` or `|` operators, and has no alias, then it returns the abstract syntax
    tree of that symbol unchanged.  Examples: (d), (g), and `expr: product`.
    This is decided statically, so `program: statement*` never passes through,
    not even when the input contains exactly one statement.  The inner alternatives
    that are expanded according to 5 do not count as `|` operators, so
    `a: (b | "-" b)` passes the abstract syntax tree of `b` through.

3.  **The name of the variable as head.**  If an alternative has no head and is not a
    pass-through, the name of the variable that is defined by the rule is used as head.  For example, `program: statement*`
    yields `("program", ast(s_1), ..., ast(s_n))`, and `set_expr: "{" "}"` with
    the braces ignored yields `("set_expr",)`.

4.  **Flattening.**  Groups and repetitions are flattened into the tuple of the
    alternative they occur in, as in (h) and (i).

5.  **Inner alternatives.**  An inner alternative `( ... | ... )` that does not
    occur inside a repetition or an optional part abbreviates several alternatives:
    `expr: expr ("+" | "-") product` means `expr: expr "+" product | expr "-" product`.
    These alternatives are formed before the heads are computed, so `1 - 2` yields
    `("-", ast(1), ast(2))`.  Inside a repetition or an optional part, this is not
    possible, since the head of the tuple that collects the repeated parts cannot
    depend on the input.  There, and in an alternative with an alias, the literals
    of an inner alternative do not belong to the head.  Instead, the literal that has
    been read becomes a child of the tuple, as a plain string:
    `expr: product (("+" | "-") product)*` yields
    `("expr", ast(p_1), "-", ast(p_2), "+", ast(p_3))` for `p_1 - p_2 + p_3`.  The
    child is the literal as written in the grammar, also for literals like `"and"i`
    that ignore case.  Literals that are ignored are dropped as usual.

6.  **Optional parts.**  An optional part (`[...]` or `?`) that is absent is simply
    left out of the tuple; there is no `None` placeholder.

7.  **Named tokens.**  A named token always becomes `(NAME, text)`.  The text is
    never converted, so `NUMBER` yields `("NUMBER", "42")`.  Inline regular
    expressions `/.../` in a rule are treated like named tokens.  (With
    `parse_tokens`, the value of a token is whatever the other scanner put into it.)

8.  **Aliases.**  An alias replaces the whole head.  `-> "call"` and `-> call`
    mean the same.

9.  **The three forms of `%ignore`.**
    * `%ignore WS;` (a named terminal in a statement of its own): the lexer skips the token.
      Several terminals can be listed, separated by commas: `%ignore WS, COMMENT;`.  The elements of
      the list may be any expansions without `|` and without an alias, e.g. `/\s+/`.
    * `%ignore "(", ")"` written after an alternative: these literals are dropped
      from the abstract syntax tree of *that alternative*.
    * `%ignore: "(", ")", "{", "}";` (with a colon) in a statement of its own: these literals
      are dropped from the abstract syntax trees of *all* rules.

10. **Conflicts.**  Shift/reduce conflicts are resolved by the precedence declarations
    (see 14).  The remaining shift/reduce conflicts are resolved in favour of shift and
    reported as a warning.  Reduce/reduce conflicts are errors (unless the rules
    have different priorities).  All conflicts are listed in the output file.

11. **Output file.**  If the grammar is read from a file, the output file has the
    same name with the extension `.out` and lives in the same directory
    (`expr.g` produces `expr.out`).  If the grammar is given as a string, the
    file is `grammar.out` in the current directory.  For every state it lists
    all items (kernel and closure) in the form `A → α • β  { lookaheads }`,
    followed by the actions, the gotos and the conflicts of that state.
    With `out_file=False`, no output file is written (since version 0.8.0).

12. **Start symbol.**  The start symbol is the first rule of the grammar, unless
    another start symbol is given explicitly.

13. **Merging states (optional).**  With `merge_states=True`, states with the same
    core are merged after the canonical automaton has been built, as long as this
    introduces no new conflict (also not in the successors) and, with the contextual
    lexer, does not change how the input is split into tokens.  The parser then
    accepts the same strings and builds the same trees.  By default, states are not
    merged, so the output file shows the canonical LR(1) automaton.

14. **Precedence.**  As in bison, `%left`, `%right`, `%nonassoc`, and `%precedence`
    (each in a statement of its own) list literals and terminals, optionally separated by commas.
    Every declaration is a new level with a higher precedence than the ones above it.
    A rule has the precedence of its last terminal (also if only an earlier terminal
    has a precedence), unless `%prec NAME` is written after the alternative, in front of
    an alias or `%ignore`.  `NAME` may be a name that is not a terminal (e.g. `UMINUS`);
    such a name must be used after `%prec`.  A shift/reduce conflict between a rule and a
    look-ahead token that both have a precedence is resolved by the higher precedence; on
    the same level, `%left` reduces, `%right` shifts, `%nonassoc` makes the token a
    syntax error (an explicit error entry in the table, so that merging states keeps it),
    and `%precedence` does not resolve the conflict.  Conflicts resolved by precedence
    cause no warning; the output file gives the reason in the words of bison, e.g.
    `resolved as shift ("+" < "*")`.  Precedence declarations in imported grammars are
    ignored.

15. **Semicolons.**  Every statement ends with a semicolon:  rules, definitions of terminals, and the
    statements starting with `%` (`%import`, `%ignore`, `%declare`, `%override`, `%extend`, `%left`, ...).
    Line breaks are white space.  (Until version 0.6.0, a statement ended at a line break, unless the next
    line started with `|`, as in Lark.)  The layout used in all grammars: a statement on one line has the
    `;` directly after its last token (`expr: NUMBER;`, `%ignore WS;`); a rule with several lines has the
    `;` on a line of its own, in the column of the `|`.  A grammar error that is most likely caused by a
    missing `;` gets a message that says so (`_missing_semicolon` in `load_grammar.py`):  Without the `;`,
    the name of the next rule becomes a symbol of the previous one, so the error is found at its colon.

## Scope

* The package is called `larkita`; `Larkita(grammar).parse(text)` returns a tuple.
* Kept from Lark: the grammar loader (including `%import` and `common.lark`),
  terminal definitions and priorities, and the basic and contextual lexers.
* Removed from Lark: the Earley, CYK and LALR parsers, the public
  Tree/Transformer/Visitor API, the reconstructor, tree templates, the standalone
  and nearley tools, the interactive parser, the cache, and Lark's tree-shaping
  features (`?rule`, `!rule`, `_rule`, `_TERMINAL`, placeholders for missing optionals).
  Also removed: grammar templates (`rule{x}: ...`), post-lexers (and the `Indenter`),
  lexer callbacks, `scan()`, and serialization.  Instead of a post-lexer, a scanner of one's own
  can be used with `parse_tokens` (since version 0.8.0).
* Lark's test suite is replaced by new tests (`python3 -m tests`).

## Code map

* `larkita/larkita.py`: the class `Larkita` (entry point).
* `larkita/load_grammar.py`: grammar loader; `_make_ast_spec` computes the head of an alternative,
  after `_expand_alternatives` has expanded its inner alternatives and `_mark_child_literals` has
  marked the literals that become children (clarification 5).
* `larkita/lr_analysis.py`: canonical LR(1) automaton, parse table, conflict resolution (including
  the precedence declarations, `_resolve_shift_reduce`), and the optional merging of states (`_merge_states`).
  `load_grammar.Grammar.compile` turns the precedence declarations into a dictionary from terminal names
  to levels and associativities; `Rule.prec` is the symbol after `%prec`.
* `larkita/ast_builder.py`: the reduction callbacks that build the nested tuples.
* `larkita/report.py`: writes the output file (including the sections "Precedence" and "Merged states").
* `larkita/lr_parser.py`, `larkita/lexer.py`, `larkita/parser_frontends.py`: the runtime.
  `lexer.token_collisions` decides whether merging states could change the tokens of the
  contextual lexer.
* `larkita/tree.py`, `larkita/visitors.py`, `larkita/parse_tree_builder.py`: internal, used to
  parse grammar files only.
* `larkita/pygments_lexer.py`: the Pygments lexers `larkita` and `python-larkita`, registered as plugins
  in `pyproject.toml`.  `tutorial/larkita_lexer.py` and `Lecture-Notes/larkita_lexer.py` in the course are
  copies of these classes for minted (only the docstrings differ); keep the classes identical.
* `tests/test_larkita.py`: the tests (`python3 -m tests`).
* `tutorial/`: the LaTeX tutorial (see below).

## Handoff: state of the work and how to continue

Last updated on 2026-11-27.  The memory of earlier Claude Code sessions is only stored on the home computer
(under the old directory name `simple-lark`), so this section is the reference.

### Repositories

* **Larkita**: this directory (iCloud Drive, `Box/Larkita`),
  <https://github.com/karlstroetmann/Larkita>, branch `master`.  The directory used to be called
  `simple-lark`.
* **Formal-Languages** (the course): iCloud Drive, `Box/Kurse/Formal-Languages`,
  <https://github.com/karlstroetmann/Formal-Languages>, branch `master`.
  * `Lecture-Notes/`: the LaTeX lecture notes.  Its own `CLAUDE.md` contains the author's rules.
  * `Python/Chapter-NN/`: the Jupyter notebooks, numbered like the chapters.
  * `fl.sh`: creates the conda environment `fl` and installs Larkita from PyPI.
  * The PDF of the lecture notes is not tracked.  It is the asset of the GitHub release
    `lecture-notes`.  On 2026-10-31, the history was rewritten (with `git filter-repo` and a force push)
    to remove the old versions of the PDF and of the big images; the repository shrank from 640 MB to
    43 MB.  Images are kept at about 200 dpi at their printed width.
* In both repositories, commits go directly to `master`.  Commit and push only after the author has
  agreed.  Commit messages end with the line
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

### What has been done

1. Lark has been turned into Larkita (see the specification above), with a new README and new tests.
   Later additions: `Larkita.lex()`, the tutorial, and the option `merge_states`.
2. The tutorial `tutorial/larkita-tutorial.tex` (author: Karl Stroetmann) explains grammars, the
   shape of the abstract syntax trees, pattern matching, a small interpreter, syntax errors, the
   output file, conflicts, merging states, and the API.  All listings are read from the files in
   `tutorial/examples`; the outputs shown are produced by `examples/run_examples.py` and stored in
   `examples/output` (committed).  `make` in `tutorial/` runs the examples and builds the PDF, which
   is committed, too.  The README links to the PDF.
3. Course notebooks: all notebooks that used Lark use Larkita now.  The Lark versions
   (`name-lark.ipynb`) were deleted on 2026-10-30.  Notebooks are committed without outputs.
   `Python/Chapter-11/06-Merging-States.ipynb` demonstrates `merge_states`.
4. The lecture notes describe Larkita instead of Lark: chapter 7 (`larkita.tex`), chapter 8
   (`larkita-interpreter.tex`), chapter 11 (`larkita-lalr.tex`, including the subsection 11.3.3
   "Merging States"), and chapter 13 (`compiler.tex`).  (Until 2026-10-31, these files were called
   `lark.tex`, `lark-interpreter.tex`, and `lark-lalr.tex`.)  Decisions of the author: Lark is only mentioned in a
   footnote in chapter 7; the pictures were kept and their captions adapted; the subtitle is
   "An Introduction via Larkita".
5. Larkita is published on PyPI (<https://pypi.org/project/larkita/>); the first version, 0.1.0, was
   released on 2026-10-30.  It needs Python 3.12 or newer.  See "Releasing a new version on PyPI".
6. Version 0.2.0 changes the abstract syntax trees of inner alternatives (clarification 5).  Before,
   all their literals belonged to the head, so `1 + 2` and `1 - 2` yielded the same tree for
   `expr: product (("+" | "-") product)*`.  Released on 2026-10-30.  In the course,
   `Python/Chapter-07/01-Calculator-EBNF.ipynb` uses inner alternatives inside repetitions, and the
   interpreters (chapter 8) and compilers (chapter 13) use them for the comparison, additive, and
   multiplicative operators, e.g. `expr: expr ("+" | "-") product`; the lecture notes show these
   grammars.  The notebooks of chapters 7 and 11 keep one alternative per operator on purpose.
7. Version 0.3.0 allows a list after `%ignore`, e.g. `%ignore WS, C_COMMENT, CPP_COMMENT`
   (clarification 9).  Released on 2026-10-31.  The interpreters of chapter 8, the table generators of
   chapter 10, and the listing of the interpreter's grammar in the lecture notes use it.  In
   chapter 13, the two `%ignore` directives stay apart, since each one is explained in its own cell.
8. Version 0.4.0 allows a list after `%import`, e.g. `%import common.CNAME -> ID, common.INT, common.WS`;
   every element has one of the forms of a single import.  The notebooks of chapters 7 and 8 and their
   listings in the lecture notes use it.  In the tutorial, `while.g` uses both kinds of lists, while the
   first example and the prelude of `shapes.py` keep one import per line, since the text explains the
   lines one by one.  Version 0.4.0 also gives the messages for errors in grammars in every statement:
   before, an error only matched the examples in `GRAMMAR_ERRORS` if it was in the first statement,
   since the parser's stack must have the same height (`_GRAMMAR_ERRORS_IN_ALL_POSITIONS`).  A message
   that names a token is only given for this token (`_TOKEN_SPECIFIC_ERRORS`).  Released on 2026-10-31.
9. Version 0.4.1 makes the messages "used but not defined" and "were marked to ignore but were not
   defined" independent of the hash seed:  `_find_used_symbols` returns the names in the order of their
   first occurrence instead of a set, so the first undefined name is reported, and the undefined
   terminals after `%ignore` are listed in the order in which they are written.  Released on 2026-10-31.
10. The grammar files of chapters 9 and 10 (`Python/Chapter-09/*.g`, `Python/Chapter-10/Examples/*.g`)
    are written in Larkita's notation since 2026-10-31:  literals in double quotes, alternatives separated
    by `|`, and no semicolons.  The grammars for grammars in `Earley-Parser.ipynb`,
    `LR-Table-Generator.ipynb`, and `SLR-Table-Generator.ipynb` recognize a variable that is followed by a
    colon as the token `RULE_NAME.2` (with the lookahead `(?=[ \t]*:)`), since an LR(1) parser cannot tell
    otherwise where a rule ends.  Every file yields the same rules as before.
11. Version 0.5.0 adds the Pygments lexers in `larkita/pygments_lexer.py`.  The notebooks of chapters 9
    and 10 display the grammar files with `display(Code(text, language='larkita'))`.  Released on
    2026-10-31.
12. The notebooks of chapters 7, 8, 11, and 13 no longer contain their grammars as strings:  Every grammar
    is stored in a `.lark` file next to its notebook (chapter 13: `Python/Chapter-13/Grammar/*.lark`, one
    file per piece that the notebook explains), which the notebook displays with
    `Code(filename=..., language='larkita')` and loads with `Larkita.open` (chapter 13 joins the pieces
    with its function `read_grammar`).  The grammar of the exercise solution, `Chapter-08/sl-solution.lark`,
    is listed in `Python/Chapter-08/.gitignore`.  The listings of these grammars in the lecture notes show
    the contents of the files.  Version 0.5.1 makes the `ConflictWarning` refer to the first line outside of
    Larkita (`skip_file_prefixes`); with `stacklevel=2`, the warning pointed into `Larkita.open`.
13. Version 0.6.0 adds the precedence declarations of bison (clarification 14).  Released on 2026-11-12.
    The semantics were checked against bison (2.3, the version of macOS): a rule takes the precedence of
    its last terminal, and the reasons in the output file use bison's words.  The tutorial explains them in
    the subsection "Precedence and associativity" with `examples/precedence.g`.  The Pygments lexer
    highlights the new keywords; its copies in the tutorial and in the lecture notes were updated, too.
    In the course, section 11.3 "Precedence Declarations" of the lecture notes explains them with the new
    notebook `Python/Chapter-11/03-Precedence-Declarations.ipynb` (the notebooks 03-06 of chapter 11 became
    04-07), and the compiler of chapter 13 declares the precedences of its operators instead of stratifying
    the grammar (`Python/Chapter-13/Grammar/bool-expr.lark` and `expr.lark`; the trees and the generated
    code are the same as before).  The dangling `else` of the compiler is still resolved as shift with a
    warning.
14. Version 0.7.0 ends every statement of a grammar with a semicolon (clarification 15).  Released on 2026-11-15.
    All grammars were converted by a script that finds the ends of the statements with the terminals of the
    old meta-grammar; for every converted grammar, the parse tree of the meta-grammar was compared with the
    one of the original (identical for all files and test strings).  The tutorial's outputs, the automata
    and the trees, did not change, except for the outputs of `shapes.py`, which repeat the grammars.  The
    Pygments lexer treats `;` as punctuation (before, it was an error token).  In the course, all grammar
    files, the grammars in the notebooks, and the listings in the lecture notes were converted in the same way;
    the grammars for grammars of chapters 9 and 10 no longer need the token `RULE_NAME` (item 10), since the
    `;` tells the parser where a rule ends.  The line numbers cited in the lecture notes were adapted.
15. Version 0.7.1 changes only the wording, at the author's request:  Lowercase names are syntactical
    variables, not rules, and the head of an alternative without literals is the name of the variable that is
    defined by the rule (clarification 3; README, tutorial, the error message for `%declare`).  The course was
    changed in the same way.  Released on 2026-11-15.
16. Version 0.7.2 changes only the format of the states in the output file, at the author's request:  An item
    is followed by a colon and its look-ahead tokens, without curly braces, e.g. `b → "X" •:  "U"`, like the
    notation $A \rightarrow \alpha \mdot \beta: L$ of the lecture notes.  The colon directly follows the
    item; the look-ahead tokens are aligned in a column.  The README, the tutorial (outputs and the
    explanation of a state), and the listings of states in chapter 11 of the lecture notes were updated.
    Released on 2026-11-24.
17. Version 0.7.3 changes only how a conflict is printed, at the author's request:  `repr` shows the terminal
    as it is written in the grammar, e.g. `<shift/reduce conflict in state 5 on "+">` instead of `... on PLUS`.
    `Conflict.terminal` keeps the name of the terminal; `Larkita` sets `Conflict.terminal_repr` from the
    names that the output file uses.  In the course, the notebooks of chapter 11 no longer use the module
    `warnings`; they print `len(parser.conflicts)` and rely on the `ConflictWarning` that Jupyter shows.
    Released on 2026-11-26.
18. Version 0.8.0 lets other scanners use Larkita's parser.  It was written for pytunia
    (<https://github.com/karlstroetmann/pytunia>, `Box/Pytunia`), whose parser for Jasmin is generated
    by Larkita, while the tokens come from a hand-written scanner that follows Jasmin's rules.
    * `Larkita.parse_tokens(tokens)` parses an iterable of `Token` objects, bypassing the lexer
      (`LRParser.parse_tokens`, `ParsingFrontend.parse_tokens`).  The type of a token is the name of
      a terminal.  The value can be any object; the tree contains it unchanged.  The end of the input
      is reported at the position of the last token, and `UnexpectedToken.token` is the token of the
      scanner.
    * `Larkita.literals` maps the string literals that occur in the rules to the names of their
      terminals (`_literals` in `larkita.py`), also when a literal is the pattern of a named terminal
      (`PLUS: "+"`).
    * `out_file=False` writes no output file (`parser.out_file` is then `None`); the messages about
      conflicts then do not say "see ...".  `out_file=True` means the default path, so that
      `open(True)` cannot write the report to the standard output.  Without the report, building
      the parser is faster (pytunia: 0.04 s instead of 0.07 s).
    * The tutorial has a new subsection 3.4 "Using another scanner" with `examples/scanner.py`.
      The README has a subsection with the same name.
    Released on 2026-11-27.

### Constraints

* `Python/Chapter-08/Interpreter.ipynb` is the solution of an exercise.  It is listed in
  `Python/Chapter-08/.gitignore` and must never be committed.  (It was committed once by mistake as
  `Interpreter-larkita.ipynb`; commit 05cbd84 stopped tracking it.  The author decided not to remove
  it from the history.)
* Lecture notes (details in `Lecture-Notes/CLAUDE.md`): ask before changes of taste or content;
  listings that show notebook code must match the notebook; fonts must not become smaller (wide
  listings are fixed with `gobble`, smaller margins, or by rewrapping the code in the notebook);
  new notions are written as `\blue{term}\index{term}`; `formal-languages.idx` is committed together
  with the sources, and the PDF is uploaded with
  `gh release upload lecture-notes formal-languages.pdf --clobber`.

### How to check the work

* Larkita: `python3 -m tests` (99 tests; the 3 tests of the lexers are skipped without Pygments) and
  `mypy larkita`, which needs the stubs `types-Pygments`.
* Tutorial: `cd tutorial && make`.  The build must have no errors and no overfull boxes.  The only
  accepted warnings are the two hyperref warnings "Token not allowed in a PDF string", which come from
  `\Lark` in the title of the subsection "Differences from Lark".  Grammars are set with the Pygments
  lexer `tutorial/larkita_lexer.py`, an identical copy of the lexer in the lecture notes (see
  `Lecture-Notes/CLAUDE.md` there).  minted only loads it if its SHA-256 hash is listed in
  `~/.latexminted_config`; after a change of the lexer, update the hash and delete `tutorial/_minted`.
* Lecture notes: run `pdflatex -shell-escape -interaction=nonstopmode formal-languages.tex` three
  times.  A clean build has 0 errors (`grep -c '^!' formal-languages.log`) and no "undefined" or
  "multiply defined" references.  Too wide `minted` listings produce no warnings, so check the PDF:
  `pdftotext -bbox formal-languages.pdf out.html` and look for words whose `xMax` exceeds 542 (the
  text block ends at 540pt).  The only known case is the signature of `evaluate_bool` in chapter 8,
  which stays inside its frame and is the author's code.  Render pages with
  `pdftoppm -r 70 -f N -l N -png formal-languages.pdf page` to look at them.
* Notebooks: execute them in the environment `fl` with nbclient (or
  `conda run -n fl jupyter nbconvert --to notebook --execute --output /tmp/out.ipynb X.ipynb`),
  with `PYTHONHASHSEED=0`, and never save the outputs into the repository.  Notebooks that call
  `input()` need `input` to be redefined in the notebook's global namespace (ipykernel resets
  `builtins.input`).  The outputs of `name.ipynb` and `name-lark.ipynb` were compared when the
  Larkita versions were created.
* `merge_states` was verified by fuzzing: token sequences of sample programs were mutated (deleted,
  duplicated, swapped, replaced tokens), and the canonical and the merged parser had to return the
  same trees and report errors at the same line and column.  Repeat this if the merging code changes.
  For version 0.6.0, this was repeated with grammars that use precedence declarations (including
  `%nonassoc` and a dangling `else` resolved with `%prec`); a variant that drops the error entries of
  `%nonassoc` from the comparison of states was caught at once.

### Setting up another computer

* Create the environment with `fl.sh`.  It installs Larkita from PyPI; update it with
  `conda run -n fl pip install --upgrade larkita`.  Changes that have not been released yet are
  installed from GitHub with
  `conda run -n fl pip install --upgrade --force-reinstall git+https://github.com/karlstroetmann/Larkita.git`.
  On the home computer, Larkita is installed in editable mode instead:
  `conda run -n fl pip install -e <path of this directory>`.  The plugins for Pygments are only
  registered when Larkita is installed, so run this command again after a change of the entry points in
  `pyproject.toml`.
* Needed tools: TeX Live with `minted` 3 (and Pygments) and the `atkinson` fonts, `mypy` with
  `types-Pygments`, poppler
  (`pdftotext`, `pdftoppm`), and ImageMagick (`montage`) for looking at several pages at once.
* The tutorial and the lecture notes need `~/.latexminted_config` with the hash of the lexer for
  grammars:  `{"custom_lexers": {"larkita_lexer.py": ["<shasum -a 256 tutorial/larkita_lexer.py>"]}}`.

### Releasing a new version on PyPI

1. Increase `__version__` in `larkita/__init__.py`, commit, and push.
2. Run `git tag -a vX.Y.Z -m "Larkita X.Y.Z"` and `git push origin vX.Y.Z`.

The workflow `.github/workflows/publish.yml` checks that the tag matches `__version__`, runs the tests
with Python 3.12, builds the package, and uploads it to PyPI via Trusted Publishing: PyPI trusts this
workflow, so no token is needed.  The publisher is configured in the PyPI account `KarlStroetmann`,
which uses two-factor authentication.  A version can never be uploaded twice.  `gh` is not installed
on every computer; the state of the last run is shown by
`curl -s "https://api.github.com/repos/karlstroetmann/Larkita/actions/runs?per_page=1"`.

### Open points (not started)

* The lists of expected tokens in error messages depend on the hash seed (as in Lark).  Sorting them
  would make the messages reproducible; the tutorial avoids the problem with `PYTHONHASHSEED=0`.

### How the author likes to work

* Asks for an assessment before larger changes; give a recommendation instead of a list of options.
* Ask when in doubt about questions of taste or content; report results honestly, including
  problems that were found (e.g. the contextual lexer issue found while fuzzing `merge_states`).
* Documents and comments are written in English.
