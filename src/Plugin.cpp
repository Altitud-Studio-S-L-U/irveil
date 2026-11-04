#include "irveil/Pass.h"
#include "Version.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Passes/PassPlugin.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/ErrorHandling.h"

#include <cstdint>
#include <string>

namespace {

// Clang must load the DSO before parsing -mllvm options. The installed CMake
// helper uses -Xclang -load as well as -fpass-plugin for this reason.
llvm::cl::opt<std::string> ClangSeed(
    "irveil-seed", llvm::cl::desc("IRVeil unsigned decimal seed"),
    llvm::cl::init("0"));
llvm::cl::opt<std::string> ClangMaxAdds(
    "irveil-max-adds", llvm::cl::desc("IRVeil additions per function (1..4096)"),
    llvm::cl::init("256"));
llvm::cl::opt<bool> ClangReport(
    "irveil-report", llvm::cl::desc("Report IRVeil configuration and counters"),
    llvm::cl::init(false));
llvm::cl::opt<std::string> ClangMaxInstructions(
    "irveil-max-instructions",
    llvm::cl::desc("IRVeil emitted instructions per function (9..36864)"),
    llvm::cl::init("36864"));

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
  bool seenInstructions = false;
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
    } else if (keyValue.first == "max-instructions" && !seenInstructions &&
               value >= 9 && value <= 36864) {
      config.maxInstructionsPerFunction = static_cast<std::uint32_t>(value);
      seenInstructions = true;
    } else {
      return false;
    }

    if (option.second.empty())
      return option.first.size() == name.size();
    name = option.second;
  }
  return false;
}

irveil::Config clangConfig() {
  irveil::Config config;
  std::uint64_t cap;
  if (!parseUnsignedDecimal(ClangSeed.getValue(), config.seed))
    llvm::report_fatal_error(
        "IRVeil: -irveil-seed must be an unsigned decimal integer in "
        "0..18446744073709551615", false);
  if (!parseUnsignedDecimal(ClangMaxAdds.getValue(), cap) || cap < 1 || cap > 4096)
    llvm::report_fatal_error(
        "IRVeil: -irveil-max-adds must be a decimal integer in 1..4096", false);
  config.maxAddsPerFunction = static_cast<std::uint32_t>(cap);
  if (!parseUnsignedDecimal(ClangMaxInstructions.getValue(), cap) ||
      cap < 9 || cap > 36864)
    llvm::report_fatal_error(
        "IRVeil: -irveil-max-instructions must be a decimal integer in 9..36864",
        false);
  config.maxInstructionsPerFunction = static_cast<std::uint32_t>(cap);
  return config;
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
                  manager.addPass(irveil::IRVeilPass(clangConfig(), ClangReport));
                });
          }};
}
