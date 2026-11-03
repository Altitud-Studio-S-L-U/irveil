source_filename = "selection.ll"
target triple = "x86_64-pc-linux-gnu"

@.annotation = private unnamed_addr constant [7 x i8] c"irveil\00"
@.source = private unnamed_addr constant [1 x i8] zeroinitializer
@llvm.global.annotations = appending global [4 x { ptr, ptr, ptr, i32, ptr }] [
  { ptr, ptr, ptr, i32, ptr } { ptr @protected, ptr @.annotation, ptr @.source, i32 1, ptr null },
  { ptr, ptr, ptr, i32, ptr } { ptr @flags, ptr @.annotation, ptr @.source, i32 1, ptr null },
  { ptr, ptr, ptr, i32, ptr } { ptr @excluded_widths, ptr @.annotation, ptr @.source, i32 1, ptr null },
  { ptr, ptr, ptr, i32, ptr } { ptr @external, ptr @.annotation, ptr @.source, i32 1, ptr null }
], section "llvm.metadata"

define i32 @protected(i32 %a, i32 %b) {
entry:
  %s0 = add i32 %a, %b
  %s1 = add i32 %a, %b
  %s2 = add i32 %a, %b
  %s3 = add i32 %a, %b
  %s4 = add i32 %a, %b
  %s5 = add i32 %a, %b
  %s6 = add i32 %a, %b
  %s7 = add i32 %a, %b
  %callee = call i32 @unselected(i32 %s7, i32 %b)
  ret i32 %callee
}

define i32 @flags(i32 %a, i32 %b) {
entry:
  %unsigned = add nuw i32 %a, %b
  %signed = add nsw i32 %a, %b
  %both = add nuw nsw i32 %a, %b
  %result = xor i32 %unsigned, %signed
  %combined = xor i32 %result, %both
  ret i32 %combined
}

define i32 @unselected(i32 %a, i32 %b) {
entry:
  %sum = add i32 %a, %b
  ret i32 %sum
}

define i128 @excluded_widths(i1 %a, i1 %b, i128 %x, i128 %y, <4 x i32> %v, <4 x i32> %w) {
entry:
  %boolean = add i1 %a, %b
  %wide = add i128 %x, %y
  %just_wide = add i65 7, 9
  %vector = add <4 x i32> %v, %w
  ret i128 %wide
}

declare i32 @external(i32, i32)
