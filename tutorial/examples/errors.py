from larkita import Larkita, UnexpectedInput

parser = Larkita.open('while.g')

def check(text):
    text = text.removeprefix('\n')
    try:
        parser.parse(text)
        print('no syntax errors')
    except UnexpectedInput as e:
        name = type(e).__name__
        print(f'{name} at line {e.line}, column {e.column}:')
        print(e.get_context(text))

check('''
x := 1;
while (x < 10) {
    x := x + ;
}
''')

check('''
x := 1;
print(x # 2);
''')

check('''
x := 1;
print(x)
''')
