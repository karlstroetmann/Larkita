// A reduce/reduce conflict that is resolved by a priority.

stmnt: decl ";"
     | expr ";"

decl: NAME NAME     -> "decl"
    | NAME          -> "type"

expr.2: NAME        -> "var"

%import common.CNAME -> NAME
%import common.WS
%ignore WS
