from larkita import Larkita

parser = Larkita.open('not-lalr.g', merge_states=True)
for text in ['vxy', 'wxy', 'vxz', 'wxz']:
    print(text, parser.parse(text))
