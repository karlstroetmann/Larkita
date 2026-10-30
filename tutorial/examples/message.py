from larkita import Larkita, UnexpectedInput

parser = Larkita.open('while.g')
text = '''
x := 1;
while (x < 10) {
    x := x + ;
}
'''
try:
    parser.parse(text.removeprefix('\n'))
except UnexpectedInput as e:
    print(e)
