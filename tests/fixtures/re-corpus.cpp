#include "irveil/Protect.h"
#include <cinttypes>
#include <cstdint>
#include <cstdio>

extern "C" IRVEIL_PROTECT std::uint32_t re_sum32(std::uint32_t a, std::uint32_t b) { return a + b; }
extern "C" IRVEIL_PROTECT std::uint64_t re_sum64(std::uint64_t a, std::uint64_t b) { return a + b; }
extern "C" IRVEIL_PROTECT std::uint32_t re_constant32(std::uint32_t a) { return a + 17; }
extern "C" IRVEIL_PROTECT std::uint64_t re_identical64(std::uint64_t a) { return a + a; }
extern "C" IRVEIL_PROTECT std::uint32_t re_zero32(std::uint32_t a) { return a + 0; }
extern "C" IRVEIL_PROTECT std::uint32_t re_branch32(std::uint32_t a, std::uint32_t b, std::uint32_t choice) {
  if ((choice & 1) != 0) return (a + b) ^ (a >> 3);
  return (a + (b ^ 0x51a7u)) ^ (b >> 2);
}
extern "C" IRVEIL_PROTECT std::uint64_t re_loop64(std::uint64_t a, std::uint64_t b, unsigned rounds) {
  for (unsigned i = 0; i < rounds; ++i) a = (a + b) ^ (a >> 7);
  return a;
}
extern "C" __attribute__((noinline)) std::uint64_t re_unselected64(std::uint64_t a, std::uint64_t b) { return a + b; }

static std::uint64_t next(std::uint64_t &state) {
  state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state;
}

static void evaluate(unsigned index, std::uint64_t a, std::uint64_t b) {
  std::printf("%u %08" PRIx32 " %016" PRIx64 " %08" PRIx32 " %016" PRIx64
              " %08" PRIx32 " %08" PRIx32 " %016" PRIx64 " %016" PRIx64 "\n",
              index, re_sum32(a, b), re_sum64(a, b), re_constant32(a),
              re_identical64(a), re_zero32(a), re_branch32(a, b, index),
              re_loop64(a, b, index % 9), re_unselected64(a, b));
}

int main() {
  constexpr std::uint64_t edges[] = {0, 1, 2, UINT32_MAX, UINT64_MAX, UINT64_MAX - 1,
      UINT64_C(1) << 31, (UINT64_C(1) << 31) - 1, UINT64_C(1) << 63,
      (UINT64_C(1) << 63) - 1, UINT64_C(0xaaaaaaaa55555555)};
  unsigned index = 0;
  for (auto a : edges) for (auto b : edges) evaluate(index++, a, b);
  std::uint64_t state = UINT64_C(0x5be6918a2c30d47f);
  for (unsigned i = 0; i < 512; ++i) {
    const auto a = next(state); const auto b = next(state); evaluate(index++, a, b);
  }
  return 0;
}
