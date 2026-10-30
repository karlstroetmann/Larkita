from larkita import Larkita, UnexpectedInput

canonical = Larkita.open('while.g')
merged = Larkita.open('while.g', merge_states=True,
                      out_file='while-merged.out')
basic = Larkita.open('while.g', merge_states=True, lexer='basic',
                     out_file='while-basic.out')

parsers = [('canonical', canonical),
           ('merged', merged),
           ('merged, basic lexer', basic)]
for name, parser in parsers:
    print(f'{name}: {len(parser.parse_table.states)} states')
    try:
        print('   ', parser.parse('x := 1; else := 2;')[2])
    except UnexpectedInput as e:
        print('   ', type(e).__name__, 'at column', e.column)
