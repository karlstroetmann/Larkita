// A grammar for a simple calculator.

program: stmnt*

stmnt: IDENTIFIER ":=" expr ";"
     | "print" expr ";"

expr: expr "+" product
    | expr "-" product
    | product

product: product "*" factor
       | product "/" factor
       | factor

factor: "(" expr ")"    %ignore "(", ")"
      | "-" factor      -> "neg"
      | NUMBER
      | IDENTIFIER

%import common.CNAME -> IDENTIFIER
%import common.NUMBER
%import common.WS
%ignore WS
