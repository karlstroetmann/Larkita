// The dangling else problem.

stmnt: "if" "(" NAME ")" stmnt
     | "if" "(" NAME ")" stmnt "else" stmnt
     | NAME ";"

%ignore: "(", ")"

%import common.CNAME -> NAME
%import common.WS
%ignore WS
