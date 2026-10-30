from larkita import Larkita, UnexpectedInput

parser = Larkita.open('while.g')
try:
    parser.parse('x := 1;\nwhile (x < 10) {\n    x := x + ;\n}\n')
except UnexpectedInput as e:
    print(e)
