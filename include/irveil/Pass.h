#ifndef IRVEIL_PASS_H
#define IRVEIL_PASS_H

#include "llvm/IR/PassManager.h"
#include "llvm/Support/Error.h"

#include <cstdint>

namespace irveil {

enum class Profile { Arithmetic, General };

struct Config {
  std::uint64_t seed = 0;
  // In General profile this bounds all eligible rewrites per function.
  std::uint32_t maxAddsPerFunction = 256;
  Profile profile = Profile::Arithmetic;
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
