// A grammar for assignments and arithmetic expressions.

stmnt: IDENTIFIER ":=" expr ";"    %ignore ";"
     | expr ";"

expr: expr "+" product
    | expr "-" product
    | product

product: product "*" factor
       | product "/" factor
       | factor

factor: "(" expr ")"    %ignore "(", ")"
      | NUMBER
      | IDENTIFIER

%import common.CNAME -> IDENTIFIER
%import common.NUMBER
%import common.WS
%ignore WS
