stmnt: IDENTIFIER ":=" expr ";" 
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

// Lexical definitions
%import common.CNAME -> IDENTIFIER
%import common.NUMBER
%import common.WS

// Ignore whitespace
%ignore WS
