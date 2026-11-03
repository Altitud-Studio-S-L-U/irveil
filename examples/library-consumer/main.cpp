#include <irveil/Pass.h>

#include <llvm/IR/LLVMContext.h>
#include <llvm/IR/Module.h>
#include <llvm/IR/Verifier.h>
#include <llvm/IRReader/IRReader.h>
#include <llvm/Support/Error.h>
#include <llvm/Support/SourceMgr.h>
#include <llvm/Support/raw_ostream.h>

int main(int argc, char **argv) {
  if (argc != 2) {
    llvm::errs() << "Usage: irveil-consumer input.ll\n";
    return 1;
  }

  llvm::LLVMContext context;
  llvm::SMDiagnostic diagnostic;
  auto module = llvm::parseIRFile(argv[1], diagnostic, context);
  if (!module) {
    diagnostic.print(argv[0], llvm::errs());
    return 1;
  }
  if (llvm::verifyModule(*module, &llvm::errs()))
    return 1;

  auto result = irveil::applyObfuscation(*module);
  if (!result) {
    llvm::logAllUnhandledErrors(result.takeError(), llvm::errs(), "IRVeil: ");
    return 1;
  }
  if (llvm::verifyModule(*module, &llvm::errs()))
    return 1;

  llvm::errs() << "Selected functions: " << result->selectedFunctions
               << "; changed functions: " << result->changedFunctions
               << "; rewritten additions: " << result->rewrittenAdds << '\n';
  module->print(llvm::outs(), nullptr);
  return 0;
}
