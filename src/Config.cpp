#include "Config.h"
#include <system_error>

namespace irveil {
namespace {
bool decimal(llvm::StringRef text, std::uint64_t &value) {
  if (text.empty()) return false;
  for (char c : text)
    if (c < '0' || c > '9') return false;
  return !text.getAsInteger(10, value);
}

bool parseTransforms(llvm::StringRef text, std::uint32_t &mask) {
  if (text == "none") { mask = 0; return true; }
  mask = 0;
  while (!text.empty()) {
    auto part = text.split('+');
    std::uint32_t bit = 0;
    if (part.first == "adds") bit = Adds;
    else if (part.first == "sub") bit = Subtracts;
    else if (part.first == "bitwise") bit = Bitwise;
    else if (part.first == "cmp") bit = Comparisons;
    else if (part.first == "branches") bit = Branches;
    else if (part.first == "cfg") bit = CFG;
    else if (part.first == "loops") bit = Loops;
    else if (part.first == "switch") bit = Switches;
    else if (part.first == "constants") bit = Constants;
    else if (part.first == "strings") bit = Strings;
    else return false;
    if (mask & bit) return false;
    mask |= bit;
    if (part.first.size() == text.size()) return true;
    if (part.second.empty()) return false;
    text = part.second;
  }
  return false;
}
} // namespace

std::uint32_t effectiveTransforms(const Config &config) {
  return config.transforms.value_or(config.profile == Profile::General
      ? Adds | Subtracts | Bitwise | Comparisons | Branches : Adds);
}

llvm::Error validateConfig(const Config &config) {
  if ((config.profile != Profile::Arithmetic && config.profile != Profile::General) ||
      (effectiveTransforms(config) & ~AllTransforms))
    return llvm::createStringError(std::errc::invalid_argument, "IRVeil invalid profile or transform mask");
  if (config.maxAddsPerFunction < 1 || config.maxAddsPerFunction > 4096)
    return llvm::createStringError(std::errc::invalid_argument, "IRVeil maxAddsPerFunction must be between 1 and 4096");
  if (config.maxEdgesPerFunction < 1 || config.maxEdgesPerFunction > 256 ||
      config.maxSwitchCasesPerFunction < 1 || config.maxSwitchCasesPerFunction > 256 ||
      config.maxConstantsPerFunction < 1 || config.maxConstantsPerFunction > 4096 ||
      config.maxStringBytesPerModule < 1 || config.maxStringBytesPerModule > 65536 ||
      config.maxStringLoadsPerModule < 1 || config.maxStringLoadsPerModule > 65536)
    return llvm::createStringError(std::errc::invalid_argument, "IRVeil invalid structural or data expansion limit");
  return llvm::Error::success();
}

bool parseConfigOption(llvm::StringRef key, llvm::StringRef text, Config &config) {
  if (key == "profile") {
    if (text != "arithmetic" && text != "general") return false;
    config.profile = text == "general" ? Profile::General : Profile::Arithmetic;
    return true;
  }
  if (key == "transforms") {
    std::uint32_t mask;
    if (!parseTransforms(text, mask)) return false;
    config.transforms = mask;
    return true;
  }
  std::uint64_t value;
  if (!decimal(text, value)) return false;
  if (key == "seed") { config.seed = value; return true; }
  std::uint32_t *destination = nullptr;
  std::uint64_t maximum = 4096;
  if (key == "max-adds") destination = &config.maxAddsPerFunction;
  else if (key == "max-edges") { destination = &config.maxEdgesPerFunction; maximum = 256; }
  else if (key == "max-switch-cases") { destination = &config.maxSwitchCasesPerFunction; maximum = 256; }
  else if (key == "max-constants") destination = &config.maxConstantsPerFunction;
  else if (key == "max-string-bytes") { destination = &config.maxStringBytesPerModule; maximum = 65536; }
  else if (key == "max-string-loads") { destination = &config.maxStringLoadsPerModule; maximum = 65536; }
  if (!destination || value < 1 || value > maximum) return false;
  *destination = static_cast<std::uint32_t>(value);
  return true;
}
} // namespace irveil
