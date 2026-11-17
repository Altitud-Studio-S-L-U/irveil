#include "irveil/Protect.h"
#include <cinttypes>
#include <cstdint>
#include <cstdio>

// Owned synthetic fixtures. Counts and timings are not protection scores.
extern "C" IRVEIL_PROTECT std::uint32_t re_cfg32(std::uint32_t a, std::uint32_t b) {
  if (a < b) return a == 0 ? b - 1 : (a ^ b);
  if (a == b) return a | b;
  return (a & b) + 17;
}
extern "C" IRVEIL_PROTECT std::uint32_t re_loop32(std::uint32_t a, unsigned n) {
  for (unsigned i = 0; i < n % 9; ++i) {
    if (i == 3) continue;
    for (unsigned j = 0; j < n % 5; ++j) {
      if (a == 0) break;
      a = (a - j) ^ (a >> 3);
    }
    a += i;
  }
  return a;
}
extern "C" IRVEIL_PROTECT std::uint32_t re_switch32(std::uint32_t x, unsigned choice) {
  switch (choice) {
  case 0: return x + 7;
  case 1: case 2: return x ^ 0x51a7u;
  case 13: return x - 31;
  case 255: return x | 0x80000000u;
  default: return x & 0xffffu;
  }
}
extern "C" IRVEIL_PROTECT std::uint64_t re_constant64(std::uint64_t a) {
  return (a ^ UINT64_C(0x8000000000000000)) + UINT64_C(0x7fffffffffffffff);
}
extern "C" IRVEIL_PROTECT unsigned char re_string8(unsigned index) {
  return static_cast<unsigned char>("irveil-X"[index % 9]);
}
static __attribute__((noinline)) unsigned char read_shared(const unsigned char *p, unsigned i) {
  return p[i % 9];
}
extern "C" IRVEIL_PROTECT unsigned char re_shared_string8(unsigned index) {
  static constexpr unsigned char text[] = "public-Z";
  return read_shared(text, index);
}
extern "C" __attribute__((noinline)) std::uint32_t re_unselected32(std::uint32_t a, std::uint32_t b) {
  return a + b;
}
extern "C" IRVEIL_PROTECT std::uint32_t re_bool32(std::uint32_t a, std::uint32_t b) {
  const int sa = static_cast<int>(a & 0x7fffffffu) - 1073741824;
  const int sb = static_cast<int>(b & 0x7fffffffu) - 1073741824;
  return ((a - b) ^ ((a | b) & ~(a & b))) + (sa < sb) + (sa >= sb) * 2u;
}
static void row(unsigned i, std::uint64_t a, std::uint64_t b) {
  constexpr unsigned choices[] = {0, 1, 2, 13, 255, 3, 0xffffffffu};
  std::printf("%u %08" PRIx32 " %08" PRIx32 " %08" PRIx32 " %016" PRIx64 " %02x %02x %08" PRIx32 " %08" PRIx32 "\n",
      i, re_cfg32(a, b), re_loop32(a, i), re_switch32(a, choices[i % 7]),
      re_constant64(a), re_string8(i), re_shared_string8(i), re_unselected32(a, b), re_bool32(a, b));
}
int main() {
  constexpr std::uint64_t edges[] = {0, 1, 2, UINT32_MAX, UINT64_MAX, UINT64_MAX - 1,
      UINT64_C(1) << 31, (UINT64_C(1) << 31) - 1, UINT64_C(1) << 63,
      (UINT64_C(1) << 63) - 1, UINT64_C(0xaaaaaaaa55555555)};
  unsigned i = 0;
  for (auto a : edges) for (auto b : edges) row(i++, a, b);
  std::uint64_t state = UINT64_C(0x5be6918a2c30d47f);
  for (unsigned n = 0; n < 512; ++n) {
    state ^= state << 13; state ^= state >> 7; state ^= state << 17;
    const auto a = state;
    state ^= state << 13; state ^= state >> 7; state ^= state << 17;
    row(i++, a, state);
  }
}
