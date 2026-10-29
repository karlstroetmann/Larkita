program: statement* 

statement: "function" IDENTIFIER "(" params ")" block                   
         | "if" "(" expr ")" statement                                 
         | "if" "(" expr ")" statement "else" statement                
         | "while" "(" expr ")" statement                              
         | "for" "(" assignment ";" expr ";" assignment ")" statement  
         | "return" [expr] ";"                                         
         | assignment ";"
         | expr ";"                                                    
         | block

block:     "{" program "}"
assignment: IDENTIFIER ":=" expr
params:     (IDENTIFIER ("," IDENTIFIER)*)

expr: disjunction

disjunction: disjunction "||" conjunction 
           | conjunction

conjunction: conjunction "&&" negation 
           | negation

negation: "!" negation 
        | comparison

comparison: sum "==" sum 
          | sum "!=" sum 
          | sum "<=" sum 
          | sum ">=" sum 
          | sum "<"  sum 
          | sum ">"  sum 
          | sum

sum: sum "+" product 
   | sum "-" product 
   | product

product: product "*" factor 
       | product "/" factor 
       | product "%" factor 
       | factor

factor: "-" factor -> neg
      | atom

atom: "(" expr ")"
    | NUMBER                       
    | FLOAT                        
    | STRING                       
    | IDENTIFIER                   
    | IDENTIFIER "(" expr_list ")" -> "call"
    | set_expr

expr_list: (expr ("," expr)*) 

// Sets: the empty set, an enumeration, a range, and two forms of set comprehension.
set_expr: "{" "}"                               
        | "{" expr ".." expr "}"               
        | "{" expr ("," expr)* "}"             
        | "{" expr ":" generators "}"          
        | "{" expr ":" generators "|" expr "}" 

generators: generator ("," generator)*
generator:  IDENTIFIER "in" expr

        
// Lexical definitions
%import common.CNAME -> IDENTIFIER
%import common.WS

FLOAT:  /[0-9](_?[0-9])*\.[0-9](_?[0-9])*([eE][+-]?[0-9]+)?/
NUMBER: /[0-9](_?[0-9])*/
STRING: /"(\\.|[^"\\])*"/

CPP_COMMENT: /\/\/[^\n]*/
C_COMMENT:   "/*" /(.|\n)*?/ "*/"

// Ignore whitespace and comments
%ignore WS
%ignore C_COMMENT
%ignore CPP_COMMENT
