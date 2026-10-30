"""Runs the examples of the tutorial and writes their outputs into the directory output.

The tutorial includes these files, hence the listings in the tutorial always show what the
examples actually print.  The examples use the copy of Larkita in this repository.
PYTHONHASHSEED is fixed because the order of the tokens in some error messages depends on it.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUTPUT = os.path.join(HERE, 'output')

SCRIPTS = ['first', 'lex', 'shapes', 'calc', 'while', 'errors', 'message',
           'dangling', 'look-ahead', 'priority', 'merge', 'not-lalr']


def run(name):
    env = dict(os.environ, PYTHONPATH=ROOT, PYTHONHASHSEED='0')
    result = subprocess.run([sys.executable, name + '.py'], cwd=HERE, env=env,
                            capture_output=True, text=True, encoding='utf8')
    if result.returncode != 0:
        sys.exit(f'{name}.py failed:\n{result.stderr}')
    return result.stdout + result.stderr


def write(name, text):
    with open(os.path.join(OUTPUT, name + '.txt'), 'w', encoding='utf8') as f:
        f.write(text.rstrip() + '\n')


def read(name):
    with open(os.path.join(HERE, name), encoding='utf8') as f:
        return f.read()


def section(text, title):
    """Returns the section with the given title of an output file, without its title."""
    match = re.search(r'^%s\n=+\n\n(.*?)(?=^\w+\n=+\n|\Z)' % title, text, re.S | re.M)
    return match.group(1)


def conflict_state(text):
    """Returns the number of the first state with a conflict of an output file."""
    return int(re.search(r'^State (\d+), ', section(text, 'Conflicts'), re.M).group(1))


def state(text, number):
    """Returns the description of a state of an output file."""
    header = r'^State %s(?:   \(merged from [^\n]*\))?\n'
    match = re.search(header % number + r'.*?(?=' + header % r'\d+' + r'|\Z)', text, re.S | re.M)
    return match.group(0)


def first_reason(text):
    """Returns the beginning of the section "Merged states" up to the first pair of states that
    have been kept apart, including the reasons for this pair."""
    blocks = re.split(r'\n\n(?=States \d+ and \d+\n)', section(text, 'Merged states'))
    return '\n\n'.join(blocks[:2])


def main():
    os.makedirs(OUTPUT, exist_ok=True)
    for name in SCRIPTS:
        output = run(name)
        if name == 'shapes':
            for part in output.split('#### ')[1:]:
                title, _, body = part.partition('\n')
                write('shapes-' + title, body)
        else:
            write(name, output)
    expr = read('expr.out')
    write('expr-header', expr[:expr.index('\n\n\nRules')])
    write('expr-rules', section(expr, 'Rules'))
    write('expr-state', state(expr, 2))
    dangling = read('dangling.out')
    write('dangling-conflicts', section(dangling, 'Conflicts'))
    write('dangling-state', state(dangling, conflict_state(dangling)))
    look_ahead = read('look-ahead.out')
    write('look-ahead-state', state(look_ahead, conflict_state(look_ahead)))
    write('priority-conflicts', section(read('priority.out'), 'Conflicts'))
    write('while-merged', first_reason(read('while-merged.out')))
    write('while-merged-state', state(read('while-merged.out'), 3))
    write('while-basic', section(read('while-basic.out'), 'Merged states'))
    write('not-lalr-merged', section(read('not-lalr.out'), 'Merged states'))


if __name__ == '__main__':
    main()
