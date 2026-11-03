#include "irveil/Protect.h"

#include <cerrno>
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

extern "C" IRVEIL_PROTECT std::uint64_t
irveil_demo_step(std::uint64_t a, std::uint64_t b) {
  std::uint64_t value = a + b;
  for (unsigned i = 0; i < 6; ++i) {
    const std::uint64_t offset = (b ^ (a >> (i + 1))) + i;
    if ((value & 1) != 0)
      value = (value + offset) ^ (a >> i);
    else
      value = (value + (offset ^ a)) ^ (b >> i);
  }
  return value + (a ^ b);
}

static std::uint64_t next(std::uint64_t &state) {
  state ^= state << 13;
  state ^= state >> 7;
  state ^= state << 17;
  return state;
}

int main(int argc, char **argv) {
  std::uint64_t iterations = 1'000'000;
  if (argc > 2) {
    std::fprintf(stderr, "usage: %s [positive-iterations]\n", argv[0]);
    return 1;
  }
  if (argc == 2) {
    char *end = nullptr;
    errno = 0;
    const auto parsed = std::strtoull(argv[1], &end, 10);
    if (argv[1][0] == '\0' || argv[1][0] == '-' || errno != 0 ||
        *end != '\0' || parsed == 0) {
      std::fprintf(stderr, "iterations must be a positive decimal integer\n");
      return 1;
    }
    iterations = parsed;
  }
  std::uint64_t state = UINT64_C(0x19d3a78e2b645fc1);
  std::uint64_t checksum = UINT64_C(0x7c81f436a02db953);
  for (std::uint64_t index = 0; index < iterations; ++index) {
    const std::uint64_t a = next(state);
    const std::uint64_t b = next(state);
    checksum ^= irveil_demo_step(a, b) + index;
  }
  std::printf("%016" PRIx64 "\n", checksum);
  return 0;
}
