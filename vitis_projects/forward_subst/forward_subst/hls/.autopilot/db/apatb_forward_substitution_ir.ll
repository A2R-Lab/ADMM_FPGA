; ModuleID = '/home/andrea/ADMM_FPGA/vitis_projects/forward_subst/forward_subst/hls/.autopilot/db/a.g.ld.5.gdce.bc'
source_filename = "llvm-link"
target datalayout = "e-m:e-i64:64-i128:128-i256:256-i512:512-i1024:1024-i2048:2048-i4096:4096-n8:16:32:64-S128-v16:16-v24:32-v32:32-v48:64-v96:128-v192:256-v256:256-v512:512-v1024:1024"
target triple = "fpga64-xilinx-none"

%"struct.ap_fixed<32, 16>" = type { %"struct.ap_fixed_base<32, 16>" }
%"struct.ap_fixed_base<32, 16>" = type { %"struct.ssdm_int<32, true>" }
%"struct.ssdm_int<32, true>" = type { i32 }

; Function Attrs: argmemonly noinline willreturn
define void @apatb_forward_substitution_ir(%"struct.ap_fixed<32, 16>"* noalias nocapture nonnull readonly "fpga.decayed.dim.hint"="10" %b, %"struct.ap_fixed<32, 16>"* noalias nocapture nonnull "fpga.decayed.dim.hint"="10" %x) local_unnamed_addr #0 {
entry:
  %0 = bitcast %"struct.ap_fixed<32, 16>"* %b to [10 x %"struct.ap_fixed<32, 16>"]*
  %b_copy = alloca [10 x i32], align 512
  %1 = bitcast %"struct.ap_fixed<32, 16>"* %x to [10 x %"struct.ap_fixed<32, 16>"]*
  %x_copy = alloca [10 x i32], align 512
  call fastcc void @copy_in([10 x %"struct.ap_fixed<32, 16>"]* nonnull %0, [10 x i32]* nonnull align 512 %b_copy, [10 x %"struct.ap_fixed<32, 16>"]* nonnull %1, [10 x i32]* nonnull align 512 %x_copy)
  call void @apatb_forward_substitution_hw([10 x i32]* %b_copy, [10 x i32]* %x_copy)
  call void @copy_back([10 x %"struct.ap_fixed<32, 16>"]* %0, [10 x i32]* %b_copy, [10 x %"struct.ap_fixed<32, 16>"]* %1, [10 x i32]* %x_copy)
  ret void
}

; Function Attrs: argmemonly noinline norecurse willreturn
define internal fastcc void @copy_in([10 x %"struct.ap_fixed<32, 16>"]* noalias readonly "unpacked"="0", [10 x i32]* noalias nocapture align 512 "unpacked"="1.0", [10 x %"struct.ap_fixed<32, 16>"]* noalias readonly "unpacked"="2", [10 x i32]* noalias nocapture align 512 "unpacked"="3.0") unnamed_addr #1 {
entry:
  call fastcc void @"onebyonecpy_hls.p0a10struct.ap_fixed<32, 16>.13"([10 x i32]* align 512 %1, [10 x %"struct.ap_fixed<32, 16>"]* %0)
  call fastcc void @"onebyonecpy_hls.p0a10struct.ap_fixed<32, 16>.13"([10 x i32]* align 512 %3, [10 x %"struct.ap_fixed<32, 16>"]* %2)
  ret void
}

; Function Attrs: argmemonly noinline norecurse willreturn
define void @"arraycpy_hls.p0a10struct.ap_fixed<32, 16>"([10 x %"struct.ap_fixed<32, 16>"]* %dst, [10 x %"struct.ap_fixed<32, 16>"]* readonly %src, i64 %num) local_unnamed_addr #2 {
entry:
  %0 = icmp eq [10 x %"struct.ap_fixed<32, 16>"]* %src, null
  %1 = icmp eq [10 x %"struct.ap_fixed<32, 16>"]* %dst, null
  %2 = or i1 %1, %0
  br i1 %2, label %ret, label %copy

copy:                                             ; preds = %entry
  %for.loop.cond7 = icmp sgt i64 %num, 0
  br i1 %for.loop.cond7, label %for.loop.lr.ph, label %copy.split

for.loop.lr.ph:                                   ; preds = %copy
  br label %for.loop

for.loop:                                         ; preds = %for.loop, %for.loop.lr.ph
  %for.loop.idx8 = phi i64 [ 0, %for.loop.lr.ph ], [ %for.loop.idx.next, %for.loop ]
  %src.addr.0.0.05 = getelementptr [10 x %"struct.ap_fixed<32, 16>"], [10 x %"struct.ap_fixed<32, 16>"]* %src, i64 0, i64 %for.loop.idx8, i32 0, i32 0, i32 0
  %dst.addr.0.0.06 = getelementptr [10 x %"struct.ap_fixed<32, 16>"], [10 x %"struct.ap_fixed<32, 16>"]* %dst, i64 0, i64 %for.loop.idx8, i32 0, i32 0, i32 0
  %3 = load i32, i32* %src.addr.0.0.05, align 4
  store i32 %3, i32* %dst.addr.0.0.06, align 4
  %for.loop.idx.next = add nuw nsw i64 %for.loop.idx8, 1
  %exitcond = icmp ne i64 %for.loop.idx.next, %num
  br i1 %exitcond, label %for.loop, label %copy.split

copy.split:                                       ; preds = %for.loop, %copy
  br label %ret

ret:                                              ; preds = %copy.split, %entry
  ret void
}

; Function Attrs: argmemonly noinline norecurse willreturn
define internal fastcc void @copy_out([10 x %"struct.ap_fixed<32, 16>"]* noalias "unpacked"="0", [10 x i32]* noalias nocapture readonly align 512 "unpacked"="1.0", [10 x %"struct.ap_fixed<32, 16>"]* noalias "unpacked"="2", [10 x i32]* noalias nocapture readonly align 512 "unpacked"="3.0") unnamed_addr #3 {
entry:
  call fastcc void @"onebyonecpy_hls.p0a10struct.ap_fixed<32, 16>"([10 x %"struct.ap_fixed<32, 16>"]* %0, [10 x i32]* align 512 %1)
  call fastcc void @"onebyonecpy_hls.p0a10struct.ap_fixed<32, 16>"([10 x %"struct.ap_fixed<32, 16>"]* %2, [10 x i32]* align 512 %3)
  ret void
}

; Function Attrs: argmemonly noinline norecurse willreturn
define internal fastcc void @"onebyonecpy_hls.p0a10struct.ap_fixed<32, 16>"([10 x %"struct.ap_fixed<32, 16>"]* noalias "unpacked"="0" %dst, [10 x i32]* noalias nocapture readonly align 512 "unpacked"="1.0" %src) unnamed_addr #4 {
entry:
  %0 = icmp eq [10 x %"struct.ap_fixed<32, 16>"]* %dst, null
  br i1 %0, label %ret, label %copy

copy:                                             ; preds = %entry
  call void @"arraycpy_hls.p0a10struct.ap_fixed<32, 16>.9"([10 x %"struct.ap_fixed<32, 16>"]* nonnull %dst, [10 x i32]* %src, i64 10)
  br label %ret

ret:                                              ; preds = %copy, %entry
  ret void
}

; Function Attrs: argmemonly noinline norecurse willreturn
define void @"arraycpy_hls.p0a10struct.ap_fixed<32, 16>.9"([10 x %"struct.ap_fixed<32, 16>"]* "unpacked"="0" %dst, [10 x i32]* nocapture readonly "unpacked"="1.0" %src, i64 "unpacked"="2" %num) local_unnamed_addr #2 {
entry:
  %0 = icmp eq [10 x %"struct.ap_fixed<32, 16>"]* %dst, null
  br i1 %0, label %ret, label %copy

copy:                                             ; preds = %entry
  %for.loop.cond1 = icmp sgt i64 %num, 0
  br i1 %for.loop.cond1, label %for.loop.lr.ph, label %copy.split

for.loop.lr.ph:                                   ; preds = %copy
  br label %for.loop

for.loop:                                         ; preds = %for.loop, %for.loop.lr.ph
  %for.loop.idx2 = phi i64 [ 0, %for.loop.lr.ph ], [ %for.loop.idx.next, %for.loop ]
  %src.addr.0.0.05 = getelementptr [10 x i32], [10 x i32]* %src, i64 0, i64 %for.loop.idx2
  %dst.addr.0.0.06 = getelementptr [10 x %"struct.ap_fixed<32, 16>"], [10 x %"struct.ap_fixed<32, 16>"]* %dst, i64 0, i64 %for.loop.idx2, i32 0, i32 0, i32 0
  %1 = load i32, i32* %src.addr.0.0.05, align 4
  store i32 %1, i32* %dst.addr.0.0.06, align 4
  %for.loop.idx.next = add nuw nsw i64 %for.loop.idx2, 1
  %exitcond = icmp ne i64 %for.loop.idx.next, %num
  br i1 %exitcond, label %for.loop, label %copy.split

copy.split:                                       ; preds = %for.loop, %copy
  br label %ret

ret:                                              ; preds = %copy.split, %entry
  ret void
}

; Function Attrs: argmemonly noinline norecurse willreturn
define internal fastcc void @"onebyonecpy_hls.p0a10struct.ap_fixed<32, 16>.13"([10 x i32]* noalias nocapture align 512 "unpacked"="0.0" %dst, [10 x %"struct.ap_fixed<32, 16>"]* noalias readonly "unpacked"="1" %src) unnamed_addr #4 {
entry:
  %0 = icmp eq [10 x %"struct.ap_fixed<32, 16>"]* %src, null
  br i1 %0, label %ret, label %copy

copy:                                             ; preds = %entry
  call void @"arraycpy_hls.p0a10struct.ap_fixed<32, 16>.16"([10 x i32]* %dst, [10 x %"struct.ap_fixed<32, 16>"]* nonnull %src, i64 10)
  br label %ret

ret:                                              ; preds = %copy, %entry
  ret void
}

; Function Attrs: argmemonly noinline norecurse willreturn
define void @"arraycpy_hls.p0a10struct.ap_fixed<32, 16>.16"([10 x i32]* nocapture "unpacked"="0.0" %dst, [10 x %"struct.ap_fixed<32, 16>"]* readonly "unpacked"="1" %src, i64 "unpacked"="2" %num) local_unnamed_addr #2 {
entry:
  %0 = icmp eq [10 x %"struct.ap_fixed<32, 16>"]* %src, null
  br i1 %0, label %ret, label %copy

copy:                                             ; preds = %entry
  %for.loop.cond1 = icmp sgt i64 %num, 0
  br i1 %for.loop.cond1, label %for.loop.lr.ph, label %copy.split

for.loop.lr.ph:                                   ; preds = %copy
  br label %for.loop

for.loop:                                         ; preds = %for.loop, %for.loop.lr.ph
  %for.loop.idx2 = phi i64 [ 0, %for.loop.lr.ph ], [ %for.loop.idx.next, %for.loop ]
  %src.addr.0.0.05 = getelementptr [10 x %"struct.ap_fixed<32, 16>"], [10 x %"struct.ap_fixed<32, 16>"]* %src, i64 0, i64 %for.loop.idx2, i32 0, i32 0, i32 0
  %dst.addr.0.0.06 = getelementptr [10 x i32], [10 x i32]* %dst, i64 0, i64 %for.loop.idx2
  %1 = load i32, i32* %src.addr.0.0.05, align 4
  store i32 %1, i32* %dst.addr.0.0.06, align 4
  %for.loop.idx.next = add nuw nsw i64 %for.loop.idx2, 1
  %exitcond = icmp ne i64 %for.loop.idx.next, %num
  br i1 %exitcond, label %for.loop, label %copy.split

copy.split:                                       ; preds = %for.loop, %copy
  br label %ret

ret:                                              ; preds = %copy.split, %entry
  ret void
}

declare i8* @malloc(i64)

declare void @free(i8*)

declare void @apatb_forward_substitution_hw([10 x i32]*, [10 x i32]*)

; Function Attrs: argmemonly noinline norecurse willreturn
define internal fastcc void @copy_back([10 x %"struct.ap_fixed<32, 16>"]* noalias "unpacked"="0", [10 x i32]* noalias nocapture readonly align 512 "unpacked"="1.0", [10 x %"struct.ap_fixed<32, 16>"]* noalias "unpacked"="2", [10 x i32]* noalias nocapture readonly align 512 "unpacked"="3.0") unnamed_addr #3 {
entry:
  call fastcc void @"onebyonecpy_hls.p0a10struct.ap_fixed<32, 16>"([10 x %"struct.ap_fixed<32, 16>"]* %2, [10 x i32]* align 512 %3)
  ret void
}

declare void @forward_substitution_hw_stub(%"struct.ap_fixed<32, 16>"* noalias nocapture nonnull readonly, %"struct.ap_fixed<32, 16>"* noalias nocapture nonnull)

define void @forward_substitution_hw_stub_wrapper([10 x i32]*, [10 x i32]*) #5 {
entry:
  %2 = call i8* @malloc(i64 40)
  %3 = bitcast i8* %2 to [10 x %"struct.ap_fixed<32, 16>"]*
  %4 = call i8* @malloc(i64 40)
  %5 = bitcast i8* %4 to [10 x %"struct.ap_fixed<32, 16>"]*
  call void @copy_out([10 x %"struct.ap_fixed<32, 16>"]* %3, [10 x i32]* %0, [10 x %"struct.ap_fixed<32, 16>"]* %5, [10 x i32]* %1)
  %6 = bitcast [10 x %"struct.ap_fixed<32, 16>"]* %3 to %"struct.ap_fixed<32, 16>"*
  %7 = bitcast [10 x %"struct.ap_fixed<32, 16>"]* %5 to %"struct.ap_fixed<32, 16>"*
  call void @forward_substitution_hw_stub(%"struct.ap_fixed<32, 16>"* %6, %"struct.ap_fixed<32, 16>"* %7)
  call void @copy_in([10 x %"struct.ap_fixed<32, 16>"]* %3, [10 x i32]* %0, [10 x %"struct.ap_fixed<32, 16>"]* %5, [10 x i32]* %1)
  call void @free(i8* %2)
  call void @free(i8* %4)
  ret void
}

attributes #0 = { argmemonly noinline willreturn "fpga.wrapper.func"="wrapper" }
attributes #1 = { argmemonly noinline norecurse willreturn "fpga.wrapper.func"="copyin" }
attributes #2 = { argmemonly noinline norecurse willreturn "fpga.wrapper.func"="arraycpy_hls" }
attributes #3 = { argmemonly noinline norecurse willreturn "fpga.wrapper.func"="copyout" }
attributes #4 = { argmemonly noinline norecurse willreturn "fpga.wrapper.func"="onebyonecpy_hls" }
attributes #5 = { "fpga.wrapper.func"="stub" }

!llvm.dbg.cu = !{}
!llvm.ident = !{!0, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1, !1}
!llvm.module.flags = !{!2, !3, !4}
!blackbox_cfg = !{!5}

!0 = !{!"AMD/Xilinx clang version 16.0.6"}
!1 = !{!"clang version 7.0.0 "}
!2 = !{i32 2, !"Dwarf Version", i32 4}
!3 = !{i32 2, !"Debug Info Version", i32 3}
!4 = !{i32 1, !"wchar_size", i32 4}
!5 = !{}
