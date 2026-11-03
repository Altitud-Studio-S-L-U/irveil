source_filename = "unannotated.ll"
target triple = "x86_64-pc-linux-gnu"

define i32 @plain(i32 %a, i32 %b) {
  %sum = add i32 %a, %b
  ret i32 %sum
}
