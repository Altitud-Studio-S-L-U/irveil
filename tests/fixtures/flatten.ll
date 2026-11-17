source_filename = "flatten.ll"
target triple = "x86_64-pc-linux-gnu"
@.annotation = private unnamed_addr constant [7 x i8] c"irveil\00"
@.source = private unnamed_addr constant [1 x i8] zeroinitializer
@llvm.global.annotations = appending global [1 x { ptr, ptr, ptr, i32, ptr }] [
  { ptr, ptr, ptr, i32, ptr } { ptr @flat, ptr @.annotation, ptr @.source, i32 1, ptr null }
], section "llvm.metadata"

define i32 @flat(i32 %n, i32 %a, i32 %b) {
entry:
  br label %header
header:
  %i = phi i32 [ 0, %entry ], [ %next, %latch ]
  %x = phi i32 [ %a, %entry ], [ %y, %latch ]
  %y = phi i32 [ %b, %entry ], [ %sum, %latch ]
  %more = icmp ult i32 %i, %n
  br i1 %more, label %body, label %exit
body:
  %odd = and i32 %i, 1
  %choice = icmp ne i32 %odd, 0
  br i1 %choice, label %step, label %latch
step:
  %extra = xor i32 %x, %y
  br label %latch
latch:
  %delta = phi i32 [ %x, %body ], [ %extra, %step ]
  %sum = add i32 %delta, %y
  %next = add i32 %i, 1
  br label %header
exit:
  %result = xor i32 %x, %y
  ret i32 %result
}
