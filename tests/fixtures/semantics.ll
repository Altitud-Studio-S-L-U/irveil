source_filename = "semantics.ll"
target triple = "x86_64-pc-linux-gnu"

@.annotation = private unnamed_addr constant [7 x i8] c"irveil\00"
@.source = private unnamed_addr constant [1 x i8] zeroinitializer
@llvm.global.annotations = appending global [6 x { ptr, ptr, ptr, i32, ptr }] [
  { ptr, ptr, ptr, i32, ptr } { ptr @add32, ptr @.annotation, ptr @.source, i32 1, ptr null },
  { ptr, ptr, ptr, i32, ptr } { ptr @add64, ptr @.annotation, ptr @.source, i32 1, ptr null },
  { ptr, ptr, ptr, i32, ptr } { ptr @signed32, ptr @.annotation, ptr @.source, i32 1, ptr null },
  { ptr, ptr, ptr, i32, ptr } { ptr @signed64, ptr @.annotation, ptr @.source, i32 1, ptr null },
  { ptr, ptr, ptr, i32, ptr } { ptr @unsigned32, ptr @.annotation, ptr @.source, i32 1, ptr null },
  { ptr, ptr, ptr, i32, ptr } { ptr @unsigned64, ptr @.annotation, ptr @.source, i32 1, ptr null }
], section "llvm.metadata"

define i32 @add32(i32 %a, i32 %b) {
  %sum = add i32 %a, %b
  ret i32 %sum
}
define i64 @add64(i64 %a, i64 %b) {
  %sum = add i64 %a, %b
  ret i64 %sum
}
define i32 @signed32(i32 %a, i32 %b) {
  %sum = add nsw i32 %a, %b
  ret i32 %sum
}
define i64 @signed64(i64 %a, i64 %b) {
  %sum = add nsw i64 %a, %b
  ret i64 %sum
}
define i32 @unsigned32(i32 %a, i32 %b) {
  %sum = add nuw i32 %a, %b
  ret i32 %sum
}
define i64 @unsigned64(i64 %a, i64 %b) {
  %sum = add nuw i64 %a, %b
  ret i64 %sum
}
