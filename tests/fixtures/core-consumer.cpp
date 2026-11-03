#include "irveil/Pass.h"

#include <llvm/IR/Constants.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/LLVMContext.h>
#include <llvm/IR/Module.h>
#include <llvm/IR/Verifier.h>
#include <llvm/Support/Error.h>
#include <llvm/Support/raw_ostream.h>

int main() {
  llvm::LLVMContext context;
  llvm::Module module("independent-consumer", context);
  auto *i32 = llvm::Type::getInt32Ty(context);
  auto *function = llvm::Function::Create(
      llvm::FunctionType::get(i32, {i32, i32}, false),
      llvm::GlobalValue::ExternalLinkage, "consumer_protected", module);
  auto argument = function->arg_begin();
  llvm::Value *a = &*argument++;
  llvm::Value *b = &*argument;
  llvm::IRBuilder<> builder(llvm::BasicBlock::Create(context, "entry", function));
  builder.CreateRet(builder.CreateAdd(a, b));

  auto *annotation = llvm::ConstantDataArray::getString(context, "irveil");
  auto *text = new llvm::GlobalVariable(
      module, annotation->getType(), true, llvm::GlobalValue::PrivateLinkage,
      annotation, "annotation");
  auto *pointer = llvm::PointerType::getUnqual(context);
  auto *entryType = llvm::StructType::get(context, {pointer, pointer, pointer, i32, pointer});
  auto *entry = llvm::ConstantStruct::get(
      entryType, {function, text, llvm::ConstantPointerNull::get(pointer),
                  llvm::ConstantInt::get(i32, 1), llvm::ConstantPointerNull::get(pointer)});
  auto *arrayType = llvm::ArrayType::get(entryType, 1);
  new llvm::GlobalVariable(
      module, arrayType, false, llvm::GlobalValue::AppendingLinkage,
      llvm::ConstantArray::get(arrayType, {entry}), "llvm.global.annotations");

  for (auto cap : {0u, 4097u}) {
    irveil::Config invalid;
    invalid.maxAddsPerFunction = cap;
    auto rejected = irveil::applyObfuscation(module, invalid);
    if (rejected) return 1;
    llvm::consumeError(rejected.takeError());
  }
  auto transformed = irveil::applyObfuscation(module, {});
  if (!transformed) {
    llvm::logAllUnhandledErrors(transformed.takeError(), llvm::errs());
    return 2;
  }
  if (transformed->selectedFunctions != 1 || transformed->changedFunctions != 1 ||
      transformed->rewrittenAdds != 1 || llvm::verifyModule(module, &llvm::errs()))
    return 3;
  auto repeated = irveil::applyObfuscation(module, {});
  if (!repeated) {
    llvm::logAllUnhandledErrors(repeated.takeError(), llvm::errs());
    return 4;
  }
  if (repeated->changedFunctions != 0 || repeated->rewrittenAdds != 0 ||
      llvm::verifyModule(module, &llvm::errs()))
    return 5;
  llvm::outs() << "core consumer: one rewrite; second pass unchanged; invalid caps rejected\n";
  return 0;
}
