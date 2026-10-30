// An unambiguous grammar that is not LR(1).

a: b "U" "V"
 | c "U" "W"
b: "X"
c: "X"
