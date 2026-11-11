import warnings
from larkita import Larkita, UnexpectedToken

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter('always')
    parser = Larkita.open('precedence.g')
print(f'{len(parser.conflicts)} conflicts, {len(caught)} warnings')

for text in ['1 + 2 * 3', '1 - 2 - 3', '2 ^ 3 ^ 2', '-2 ^ 2',
             '-2 * 3', '1 + 2 < 3', '1 < 2 < 3']:
    try:
        print(f'{text:9}  {parser.parse(text)}')
    except UnexpectedToken as e:
        print(f'{text:9}  syntax error at column {e.column}')
