from larkita import Larkita, UnexpectedInput

parser = Larkita.open('while.g')

def check(text):
    try:
        parser.parse(text)
        print('no syntax errors')
    except UnexpectedInput as e:
        name = type(e).__name__
        print(f'{name} at line {e.line}, column {e.column}:')
        print(e.get_context(text))

check('x := 1;\nwhile (x < 10) {\n    x := x + ;\n}\n')
check('x := 1;\nprint(x # 2);\n')
check('x := 1;\nprint(x)\n')
