import re
from pprint import pprint
from larkita import Larkita, Token

parser = Larkita.open('expr.g', out_file=False)

def scan(text):
    "Splits a line into tokens; numbers become integers."
    for m in re.finditer(r'(\d+)|([A-Za-z_]\w*)|:=|\S', text):
        number, name = m.groups()
        if number:
            kind, value = 'NUMBER', int(number)
        elif name:
            kind, value = 'IDENTIFIER', name
        else:
            value = m.group()
            kind = parser.literals.get(value, value)
        yield Token(kind, value, line=1, column=m.start() + 1)

pprint(parser.parse_tokens(scan('x := (a + 3) * b;')), width=60)
