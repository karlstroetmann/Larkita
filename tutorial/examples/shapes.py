"""Demonstrates how Larkita builds abstract syntax trees.

Every call of show() prints a grammar followed by the abstract syntax trees of some strings.
The lines starting with "####" separate the examples; run_examples.py writes every example
into a file of its own.
"""
import os
from larkita import Larkita

LEXICAL = r'''
%import common.CNAME -> NAME
%import common.INT -> NUM
%import common.WS
%ignore WS
'''


def show(name, grammar, *texts):
    print('####', name)
    print(grammar.strip())
    print()
    parser = Larkita(grammar + LEXICAL, out_file=os.devnull)
    width = max(len(repr(text)) for text in texts)
    lines = [(f'{text!r:{width}}', f'⇒ {parser.parse(text)}') for text in texts]
    if all(len(text) + len(ast) < 66 for text, ast in lines):
        for text, ast in lines:
            print(text, ast)
    else:  # print every abstract syntax tree on a line of its own
        for text, ast in lines:
            print(text.rstrip())
            print('   ', ast)


show('head', r'''
sum: NUM "+" NUM
''', '1 + 2')

show('heads', r'''
assign: NAME ":=" NUM ";"
''', 'x := 1;')

show('pass-through', r'''
sum: sum "+" atom
   | atom
atom: NUM
    | NAME
''', '42', 'x + 1', '1 + 2 + 3')

show('rule-name', r'''
program: stmnt*
stmnt: NAME ";"
''', 'a; b;', 'a;', '')

show('flatten', r'''
list: "[" NUM ("," NUM)* "]"
''', '[1, 2, 3]', '[1]')

show('optional', r'''
ret: "return" [NUM] ";"
''', 'return 1;', 'return;')

show('alternatives', r'''
sum: sum ("+" | "-") NUM
   | NUM
''', '1 - 2', '1 + 2 - 3')

show('alternatives-repeated', r'''
sum: NUM (("+" | "-") NUM)*
''', '1 - 2', '1 + 2 - 3', '1')

show('ignore', r'''
sum: sum "+" atom
   | atom
atom: "(" sum ")"    %ignore "(", ")"
    | NUM
''', '(1 + 2) + 3', '((1))')

show('ignore-global', r'''
list: "[" NUM ("," NUM)* "]"
%ignore: "[", "]", ","
''', '[1, 2, 3]', '[1]')

show('alias', r'''
expr: NAME "(" NAME ")"    -> call
    | "-" NUM              -> "neg"
    | NUM "-" NUM
''', 'f(x)', '-1', '2 - 1')
