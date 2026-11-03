#include "irveil/Pass.h"
#include "Version.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Passes/PassPlugin.h"

#include <cstdint>

namespace {

bool parseUnsignedDecimal(llvm::StringRef text, std::uint64_t &value) {
  if (text.empty())
    return false;
  for (char character : text)
    if (character < '0' || character > '9')
      return false;
  return !text.getAsInteger(10, value);
}

bool parsePipelineName(llvm::StringRef name, irveil::Config &config) {
  if (name == "irveil")
    return true;
  if (!name.consume_front("irveil<") || !name.consume_back(">") ||
      name.empty())
    return false;

  bool seenSeed = false;
  bool seenCap = false;
  while (!name.empty()) {
    const auto option = name.split(';');
    const auto keyValue = option.first.split('=');
    std::uint64_t value;
    if (!parseUnsignedDecimal(keyValue.second, value))
      return false;

    if (keyValue.first == "seed" && !seenSeed) {
      config.seed = value;
      seenSeed = true;
    } else if (keyValue.first == "max-adds" && !seenCap && value >= 1 &&
               value <= 4096) {
      config.maxAddsPerFunction = static_cast<std::uint32_t>(value);
      seenCap = true;
    } else {
      return false;
    }

    if (option.second.empty())
      return option.first.size() == name.size();
    name = option.second;
  }
  return false;
}

} // namespace

extern "C" LLVM_ATTRIBUTE_WEAK llvm::PassPluginLibraryInfo
llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "IRVeil", IRVEIL_VERSION_STRING,
          [](llvm::PassBuilder &builder) {
            builder.registerPipelineParsingCallback(
                [](llvm::StringRef name, llvm::ModulePassManager &manager,
                   llvm::ArrayRef<llvm::PassBuilder::PipelineElement> inner) {
                  irveil::Config config;
                  if (!inner.empty() || !parsePipelineName(name, config))
                    return false;
                  manager.addPass(irveil::IRVeilPass(config));
                  return true;
                });
            builder.registerOptimizerLastEPCallback(
                [](llvm::ModulePassManager &manager, llvm::OptimizationLevel) {
                  manager.addPass(irveil::IRVeilPass());
                });
          }};
}
