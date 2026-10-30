from larkita import Larkita

parser = Larkita.open('priority.g')
print(parser.parse('int x;'))
print(parser.parse('x;'))
