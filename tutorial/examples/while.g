// A grammar for a small imperative language.

program: stmnt*

stmnt: IDENTIFIER ":=" expr ";"
     | "print" "(" expr ")" ";"
     | "if" "(" cond ")" stmnt "else" stmnt    -> "if"
     | "while" "(" cond ")" stmnt
     | "{" stmnt* "}"                          -> block

cond: expr "==" expr
    | expr "!=" expr
    | expr "<"  expr
    | expr "<=" expr

expr: expr "+" product
    | expr "-" product
    | product

product: product "*" factor
       | product "/" factor
       | product "%" factor
       | factor

factor: "(" expr ")"
      | NUMBER
      | IDENTIFIER

%ignore: "(", ")", "{", "}", ";"

%import common.CNAME -> IDENTIFIER
%import common.INT -> NUMBER
%import common.CPP_COMMENT
%import common.WS
%ignore CPP_COMMENT
%ignore WS
