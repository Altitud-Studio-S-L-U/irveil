#ifndef IRVEIL_CONFIG_H
#define IRVEIL_CONFIG_H

#include "irveil/Pass.h"
#include "llvm/ADT/StringRef.h"

namespace irveil {
std::uint32_t effectiveTransforms(const Config &config);
llvm::Error validateConfig(const Config &config);
bool parseConfigOption(llvm::StringRef key, llvm::StringRef value, Config &config);
} // namespace irveil
#endif
