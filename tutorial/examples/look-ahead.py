from larkita import Larkita, GrammarError

try:
    parser = Larkita.open('look-ahead.g')
except GrammarError as e:
    print(e)

parser = Larkita.open('look-ahead-solved.g')
print(parser.parse('XUV'))
print(parser.parse('XUW'))
