"""Failure controls for flattening evidence, independent of Ghidra availability."""
import unittest

from flatten import decompiler_limits, ir_facts, native_facts


class FlattenEvidenceControls(unittest.TestCase):
    def test_marker_alone_does_not_establish_dispatch_survival(self):
        original = '''define i32 @re_test(i32 %n) #0 {
entry:
  br label %dispatch
dispatch:
  %7 = phi i32 [ 1, %entry ]
  switch i32 %7, label %invalid [i32 1, label %exit]
exit:
  ret i32 %n
invalid:
  unreachable
}
attributes #0 = { "irveil.flattened" }
'''
        facts = ir_facts(original, ["re_test"])["re_test"]
        self.assertTrue(facts["flattenedAttribute"])
        self.assertEqual(facts["i32PhiSwitches"], 1)
        simplified = '''define i32 @re_test(i32 %n) #0 {
  ret i32 %n
}
attributes #0 = { "irveil.flattened" }
'''
        facts = ir_facts(simplified, ["re_test"])["re_test"]
        self.assertTrue(facts["flattenedAttribute"])
        self.assertEqual(facts["i32PhiSwitches"], 0)
        self.assertEqual(facts["switchInstructions"], 0)
        with self.assertRaisesRegex(ValueError, "missing"):
            ir_facts(original, ["re_absent"])

    def test_native_observations_require_the_requested_symbol(self):
        disassembly = '''0000000000401000 <re_test>:
  401000: movl %edi, %eax
  401002: jmpq *%rax
  401004: jne 0x401000 <re_test>
  401008: nopl (%rax)
0000000000401010 <other>:
  401010: jmpq *%rax
'''
        spec = {"id": "re_test", "address": "401000", "size": 8}
        facts = native_facts(disassembly, [spec])["re_test"]
        self.assertEqual(facts, {"symbolBytes": 8, "symbolInstructions": 3,
                                 "indirectJumps": 1, "backwardBranches": 1})
        with self.assertRaisesRegex(ValueError, "missing"):
            native_facts(disassembly, [{**spec, "id": "re_absent"}])
        with self.assertRaisesRegex(ValueError, "address"):
            native_facts(disassembly, [{**spec, "address": "402000"}])

    def test_partial_decompilation_is_flagged_separately_from_native_cost(self):
        text = '''/* WARNING: Could not recover jumptable */
void FUN_00401000(uint n) { /* Treating indirect jump as call */ }
'''
        self.assertEqual(decompiler_limits(text), {
            "unrecoveredJumpTable": True, "voidReturnInNonVoidCorpus": True})
        self.assertEqual(decompiler_limits("uint FUN_00401000(uint n) { return n; }"), {
            "unrecoveredJumpTable": False, "voidReturnInNonVoidCorpus": False})


if __name__ == "__main__":
    unittest.main()
