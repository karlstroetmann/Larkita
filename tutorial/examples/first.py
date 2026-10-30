from pprint import pprint
from larkita import Larkita

parser = Larkita.open('expr.g')
ast = parser.parse('x := (a + 3) * b;')
pprint(ast, width=60)
