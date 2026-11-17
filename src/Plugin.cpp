#include "irveil/Pass.h"
#include "Config.h"
#include "Version.h"

#include "llvm/ADT/StringSet.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Passes/PassPlugin.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/ErrorHandling.h"

#include <string>

namespace {
// Load the DSO with -Xclang -load before Clang parses -mllvm options.
llvm::cl::opt<std::string> ClangSeed("irveil-seed", llvm::cl::init("0"));
llvm::cl::opt<std::string> ClangMaxAdds("irveil-max-adds", llvm::cl::init("256"));
llvm::cl::opt<std::string> ClangProfile("irveil-profile", llvm::cl::init("arithmetic"));
llvm::cl::opt<std::string> ClangTransforms("irveil-transforms", llvm::cl::init(""));
llvm::cl::opt<std::string> ClangMaxEdges("irveil-max-edges", llvm::cl::init("32"));
llvm::cl::opt<std::string> ClangMaxSwitchCases("irveil-max-switch-cases", llvm::cl::init("64"));
llvm::cl::opt<std::string> ClangMaxConstants("irveil-max-constants", llvm::cl::init("32"));
llvm::cl::opt<std::string> ClangMaxStringBytes("irveil-max-string-bytes", llvm::cl::init("4096"));
llvm::cl::opt<std::string> ClangMaxStringLoads("irveil-max-string-loads", llvm::cl::init("4096"));
llvm::cl::opt<bool> ClangReport("irveil-report", llvm::cl::init(false));

bool parsePipelineName(llvm::StringRef name, irveil::Config &config) {
  if (name == "irveil") return true;
  if (!name.consume_front("irveil<") || !name.consume_back(">") || name.empty()) return false;
  llvm::StringSet<> seen;
  while (!name.empty()) {
    auto option = name.split(';');
    auto keyValue = option.first.split('=');
    if (!seen.insert(keyValue.first).second ||
        !irveil::parseConfigOption(keyValue.first, keyValue.second, config)) return false;
    if (option.first.size() == name.size()) return true;
    if (option.second.empty()) return false;
    name = option.second;
  }
  return false;
}

irveil::Config clangConfig() {
  irveil::Config config;
  const auto parse = [&](llvm::StringRef key, llvm::StringRef value) {
    if (irveil::parseConfigOption(key, value, config)) return;
    if (key == "seed")
      llvm::report_fatal_error("IRVeil: -irveil-seed must be an unsigned decimal integer in 0..18446744073709551615", false);
    if (key == "max-adds")
      llvm::report_fatal_error("IRVeil: -irveil-max-adds must be a decimal integer in 1..4096", false);
    llvm::report_fatal_error(llvm::Twine("IRVeil: invalid -irveil-") + key + "=" + value, false);
  };
  parse("seed", ClangSeed.getValue());
  parse("max-adds", ClangMaxAdds.getValue());
  parse("profile", ClangProfile.getValue());
  // An explicitly empty value is malformed, unlike an omitted option.
  if (ClangTransforms.getNumOccurrences()) parse("transforms", ClangTransforms.getValue());
  parse("max-edges", ClangMaxEdges.getValue());
  parse("max-switch-cases", ClangMaxSwitchCases.getValue());
  parse("max-constants", ClangMaxConstants.getValue());
  parse("max-string-bytes", ClangMaxStringBytes.getValue());
  parse("max-string-loads", ClangMaxStringLoads.getValue());
  return config;
}
} // namespace

extern "C" LLVM_ATTRIBUTE_WEAK llvm::PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "IRVeil", IRVEIL_VERSION_STRING,
          [](llvm::PassBuilder &builder) {
            builder.registerPipelineParsingCallback(
                [](llvm::StringRef name, llvm::ModulePassManager &manager,
                   llvm::ArrayRef<llvm::PassBuilder::PipelineElement> inner) {
                  irveil::Config config;
                  if (!inner.empty() || !parsePipelineName(name, config)) return false;
                  manager.addPass(irveil::IRVeilPass(config));
                  return true;
                });
            builder.registerOptimizerLastEPCallback(
                [](llvm::ModulePassManager &manager, llvm::OptimizationLevel) {
                  manager.addPass(irveil::IRVeilPass(clangConfig(), ClangReport));
                });
          }};
}
