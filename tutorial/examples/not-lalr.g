// A grammar that is LR(1), but not LALR(1).

s: "v" a "y"
 | "w" b "y"
 | "v" b "z"
 | "w" a "z"

a: "x"    -> a
b: "x"    -> b
