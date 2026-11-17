#ifndef IRVEIL_PASS_H
#define IRVEIL_PASS_H

#include "llvm/IR/PassManager.h"
#include "llvm/Support/Error.h"

#include <cstdint>
#include <optional>

namespace irveil {

enum class Profile { Arithmetic, General };

enum Transform : std::uint32_t {
  Adds = 1u << 0, Subtracts = 1u << 1, Bitwise = 1u << 2,
  Comparisons = 1u << 3, Branches = 1u << 4, CFG = 1u << 5,
  Loops = 1u << 6, Switches = 1u << 7, Constants = 1u << 8,
  Strings = 1u << 9
};
constexpr std::uint32_t AllTransforms = (1u << 10) - 1;

struct Config {
  std::uint64_t seed = 0;
  // Legacy name: bounds original instruction rewrites per function, and
  // independently the number of lowered switches, with any explicit mask.
  std::uint32_t maxAddsPerFunction = 256;
  Profile profile = Profile::Arithmetic;
  // An explicit mask replaces the profile's defaults; zero disables all work.
  std::optional<std::uint32_t> transforms;
  std::uint32_t maxEdgesPerFunction = 32;
  std::uint32_t maxSwitchCasesPerFunction = 64;
  std::uint32_t maxConstantsPerFunction = 32;
  std::uint32_t maxStringBytesPerModule = 4096;
};

struct Statistics {
  // Unique annotated definitions, including functions processed by an earlier run.
  std::uint64_t selectedFunctions = 0;
  std::uint64_t changedFunctions = 0;
  std::uint64_t rewrittenAdds = 0;
  std::uint64_t rewrittenSubtracts = 0;
  std::uint64_t rewrittenBitwise = 0;
  std::uint64_t rewrittenComparisons = 0;
  std::uint64_t rewrittenBranches = 0;
  std::uint64_t routedCFGEdges = 0;
  std::uint64_t routedLoopEdges = 0;
  std::uint64_t loweredSwitches = 0;
  std::uint64_t encodedConstants = 0;
  std::uint64_t encodedStrings = 0;
  std::uint64_t encodedStringBytes = 0;
};

// Selects functions carrying Clang's annotate("irveil") in llvm.global.annotations.
// A cap outside [1, 4096] returns an error before inspecting or mutating the module.
// Functions rewritten by an earlier run are left unchanged, regardless of seed.
llvm::Expected<Statistics> applyObfuscation(llvm::Module &module,
                                          Config config = {});

class IRVeilPass : public llvm::PassInfoMixin<IRVeilPass> {
public:
  explicit IRVeilPass(Config config = {}, bool report = false)
      : config_(config), report_(report) {}

  llvm::PreservedAnalyses run(llvm::Module &module,
                              llvm::ModuleAnalysisManager &analysisManager);

  static bool isRequired() { return true; }

private:
  Config config_;
  bool report_;
};

} // namespace irveil

#endif
