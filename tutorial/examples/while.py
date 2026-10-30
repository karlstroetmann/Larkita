import operator
from pprint import pprint
from larkita import Larkita

parser = Larkita.open('while.g')

OPERATORS = {
    '+':  operator.add, '-':  operator.sub, '*': operator.mul,
    '/':  operator.floordiv, '%': operator.mod,
    '==': operator.eq, '!=': operator.ne,
    '<':  operator.lt, '<=': operator.le,
}


def evaluate(expr, values):
    match expr:
        case ('NUMBER', digits):
            return int(digits)
        case ('IDENTIFIER', name):
            return values[name]
        case (op, lhs, rhs):
            x, y = evaluate(lhs, values), evaluate(rhs, values)
            return OPERATORS[op](x, y)


def execute(stmnt, values):
    match stmnt:
        case ('program' | 'block', *body):
            for s in body:
                execute(s, values)
        case (':=', ('IDENTIFIER', name), expr):
            values[name] = evaluate(expr, values)
        case ('print', expr):
            print(evaluate(expr, values))
        case ('if', cond, then_part, else_part):
            if evaluate(cond, values):
                execute(then_part, values)
            else:
                execute(else_part, values)
        case ('while', cond, body):
            while evaluate(cond, values):
                execute(body, values)


euclid = '''
// Euclid's algorithm
a := 1071;
b := 462;
while (b != 0) {
    r := a % b;
    a := b;
    b := r;
}
print(a);
'''
ast = parser.parse(euclid)
pprint(ast, width=60)
execute(ast, {})

collatz = '''
// the number of steps of the Collatz sequence starting at 27
n := 27;
steps := 0;
while (n != 1) {
    if (n % 2 == 0) { n := n / 2; } else { n := 3 * n + 1; }
    steps := steps + 1;
}
print(steps);
'''
execute(parser.parse(collatz), {})
