// The precedence and associativity of operators, as in Bison.
// A declaration has a higher precedence than those above it.

%nonassoc "<" "=="
%left "+" "-"
%left "*" "/"
%precedence UMINUS
%right "^"

expr: expr ("<" | "==" | "+" | "-" | "*" | "/" | "^") expr
    | "-" expr        %prec UMINUS -> "neg"
    | "(" expr ")"    %ignore "(", ")"
    | NUMBER

%import common.NUMBER
%import common.WS
%ignore WS
