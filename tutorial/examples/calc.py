from pprint import pprint
from larkita import Larkita

parser = Larkita.open('calc.g')


def evaluate(expr, values):
    match expr:
        case ('+', lhs, rhs):
            return evaluate(lhs, values) + evaluate(rhs, values)
        case ('-', lhs, rhs):
            return evaluate(lhs, values) - evaluate(rhs, values)
        case ('*', lhs, rhs):
            return evaluate(lhs, values) * evaluate(rhs, values)
        case ('/', lhs, rhs):
            return evaluate(lhs, values) / evaluate(rhs, values)
        case ('neg', arg):
            return -evaluate(arg, values)
        case ('NUMBER', digits):
            return float(digits)
        case ('IDENTIFIER', name):
            return values[name]


def execute(program):
    values = {}
    for stmnt in program[1:]:
        match stmnt:
            case ((':=', ';'), ('IDENTIFIER', name), expr):
                values[name] = evaluate(expr, values)
            case (('print', ';'), expr):
                print(evaluate(expr, values))


text = '''
x := 2 * (3 + 4);
print x / -4;
'''
ast = parser.parse(text)
pprint(ast, width=60)
execute(ast)
