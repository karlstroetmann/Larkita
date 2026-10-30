from larkita import Larkita

parser = Larkita.open('expr.g')
for t in parser.lex('x := 3 * (y + 1);'):
    print(f'{t.type:10} {t.value!r:5} {t.line}:{t.column}')
