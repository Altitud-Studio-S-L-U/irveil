source_filename = "undef.ll"
target triple = "x86_64-pc-linux-gnu"

@.annotation = private unnamed_addr constant [7 x i8] c"irveil\00"
@.source = private unnamed_addr constant [1 x i8] zeroinitializer
@llvm.global.annotations = appending global [1 x { ptr, ptr, ptr, i32, ptr }] [
  { ptr, ptr, ptr, i32, ptr } { ptr @undef_choice, ptr @.annotation, ptr @.source, i32 1, ptr null }
], section "llvm.metadata"

; The original result is restricted to {1, 4}. Duplicating the unfrozen %a
; in an arithmetic identity can also produce 2 or 3.
define i8 @undef_choice() {
  %a = select i1 undef, i8 0, i8 3
  %result = add i8 %a, 1
  ret i8 %result
}
