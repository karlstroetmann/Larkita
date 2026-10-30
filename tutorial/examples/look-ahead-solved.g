// The grammar of look-ahead.g, rewritten so that it is LR(1).

a: b "V"
 | c "W"
b: "X" "U"
c: "X" "U"
