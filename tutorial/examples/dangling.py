import warnings
from pprint import pprint
from larkita import Larkita

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter('always')
    parser = Larkita.open('dangling.g')
for warning in caught:
    print(f'{warning.category.__name__}: {warning.message}')

pprint(parser.parse('if (a) if (b) x; else y;'), width=60)
