program: statement* 

statement: "function" IDENTIFIER "(" params ")" block                   
         | "if" "(" expr ")" statement                                 
         | "if" "(" expr ")" statement "else" statement                
         | "while" "(" expr ")" statement                              
         | "for" "(" assignment ";" expr ";" assignment ")" statement  
         | "return" [expr] ";"                                         
         | assignment ";"
         | expr_nb ";"                                                    
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

atom: atom_nb
    | set_expr

atom_nb: "(" expr ")"
       | NUMBER
       | FLOAT
       | STRING
       | IDENTIFIER
       | IDENTIFIER "(" expr_list ")" -> "call"

// An expression statement must not start with "{", so that a statement starting with "{"
// is always a block (as in JavaScript).  Otherwise "{}" would be ambiguous: it could be an
// empty block or the empty set.  The rules ending in "_nb" ("no brace") mirror the rules
// for expr, ..., factor, but only describe the expressions that don't start with "{".
expr_nb: disjunction_nb

disjunction_nb: disjunction_nb "||" conjunction
              | conjunction_nb

conjunction_nb: conjunction_nb "&&" negation
              | negation_nb

negation_nb: "!" negation
           | comparison_nb

comparison_nb: sum_nb "==" sum
             | sum_nb "!=" sum
             | sum_nb "<=" sum
             | sum_nb ">=" sum
             | sum_nb "<"  sum
             | sum_nb ">"  sum
             | sum_nb

sum_nb: sum_nb "+" product
      | sum_nb "-" product
      | product_nb

product_nb: product_nb "*" factor
          | product_nb "/" factor
          | product_nb "%" factor
          | factor_nb

factor_nb: "-" factor -> neg
         | atom_nb

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
%import common.CNAME -> IDENTIFIER, common.WS, common.CPP_COMMENT, common.C_COMMENT

FLOAT:  /[0-9](_?[0-9])*\.[0-9](_?[0-9])*([eE][+-]?[0-9]+)?/
NUMBER: /[0-9](_?[0-9])*/
STRING: /"(\\.|[^"\\])*"/

// Ignore whitespace and comments
%ignore WS
%ignore C_COMMENT
%ignore CPP_COMMENT
