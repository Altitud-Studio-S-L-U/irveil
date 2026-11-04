#ifndef IRVEIL_PASS_H
#define IRVEIL_PASS_H

#include "llvm/IR/PassManager.h"
#include "llvm/Support/Error.h"

#include <cstdint>

namespace irveil {

struct Config {
  std::uint64_t seed = 0;
  std::uint32_t maxAddsPerFunction = 256;
  std::uint32_t maxInstructionsPerFunction = 36864;
};

struct Statistics {
  // Unique annotated definitions, including functions processed by an earlier run.
  std::uint64_t selectedFunctions = 0;
  std::uint64_t changedFunctions = 0;
  std::uint64_t rewrittenAdds = 0;
};

// Selects functions carrying Clang's annotate("irveil") in llvm.global.annotations.
// Invalid addition [1, 4096] or emitted-instruction [9, 36864] caps return an
// error before inspecting or mutating the module. Each rewrite reserves its
// exact prefix-network cost, including its two operand freezes (at most 35).
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
