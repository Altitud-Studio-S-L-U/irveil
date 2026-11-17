#include "irveil/Protect.h"
#include <cerrno>
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

// Owned synthetic control-flow fixtures. Volatile cells keep branch side effects
// observable in both variants; loop pragmas keep this bounded corpus comparable.
extern "C" IRVEIL_PROTECT std::uint32_t re_flat_branch32(
    std::uint32_t a, std::uint32_t b, volatile std::uint32_t *cell) {
  if (a & 1) { *cell = a + b; *cell = *cell ^ a; }
  else if (a < b) { *cell += b; }
  else { *cell = a - b; *cell += 7; }
  return *cell ^ b;
}
extern "C" IRVEIL_PROTECT std::uint32_t re_flat_loop32(
    std::uint32_t a, unsigned n, volatile std::uint32_t *cell) {
#pragma clang loop unroll(disable) vectorize(disable) interleave(disable)
  for (unsigned i = 0; i < n % 9; ++i) {
    if (i == 3) continue;
    if (a == 0) break;
    *cell = a;
    a = (a + *cell + i) ^ (a >> 3);
  }
  return a ^ *cell;
}
extern "C" IRVEIL_PROTECT std::uint64_t re_flat_phi64(
    std::uint64_t a, std::uint64_t b, unsigned n, volatile std::uint32_t *cell) {
#pragma clang loop unroll(disable) vectorize(disable) interleave(disable)
  for (unsigned i = 0; i < n % 11; ++i) {
    auto previous = a;
    a = b;
    b = previous + (b ^ *cell);
    *cell = static_cast<std::uint32_t>(a ^ b);
  }
  return a ^ b;
}
extern "C" IRVEIL_PROTECT std::uint32_t re_flat_memory32(
    std::uint32_t *p, std::uint32_t *q, std::uint32_t a, std::uint32_t b) {
  if (a & 1) { *p ^= a; *q += b; }
  else { *q += b; *p ^= a; }
  return *p + *q;
}
extern "C" IRVEIL_PROTECT std::uint32_t re_flat_recursive32(
    std::uint32_t a, unsigned depth, volatile std::uint32_t *cell) {
  if (depth == 0) { *cell = a; return a; }
  if (a & 1) {
    *cell ^= a;
    return re_flat_recursive32(a + depth, depth - 1, cell) + a;
  }
  *cell += depth;
  return re_flat_recursive32(a ^ depth, depth - 1, cell) ^ depth;
}
extern "C" IRVEIL_PROTECT std::uint32_t re_flat_switch32(
    std::uint32_t a, unsigned choice, volatile std::uint32_t *cell) {
  switch (choice) {
  case 0: *cell = a; break;
  case 1: case 2: *cell ^= a; *cell += 17; break;
  case 13: *cell = a - 31; break;
  case 255: *cell = a; *cell ^= 0x51a7u; break;
  default: *cell += a;
  }
  return *cell;
}
extern "C" IRVEIL_PROTECT std::uint64_t re_flat_straight64(std::uint64_t a, std::uint64_t b) {
  return (a + b) ^ (a >> 7);
}
extern "C" __attribute__((noinline)) std::uint32_t re_flat_unselected32(
    std::uint32_t a, volatile std::uint32_t *cell) {
  if (a & 1) { *cell = a; *cell += 1; } else *cell ^= a;
  return *cell;
}
static std::uint64_t next(std::uint64_t &state) {
  state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state;
}
static void row(unsigned i, std::uint64_t a, std::uint64_t b) {
  std::uint32_t cells[] = {static_cast<std::uint32_t>(a), static_cast<std::uint32_t>(b),
      static_cast<std::uint32_t>(a ^ b), static_cast<std::uint32_t>(~a)};
  constexpr unsigned choices[] = {0, 1, 2, 13, 255, 3, 0xffffffffu};
  const auto branch = re_flat_branch32(a, b, &cells[0]);
  const auto loop = re_flat_loop32(a, i, &cells[1]);
  const auto phi = re_flat_phi64(a, b, i, &cells[2]);
  const auto memory = re_flat_memory32(&cells[0], &cells[i % 2 ? 0 : 3], a, b);
  const auto recursive = re_flat_recursive32(a, i % 6, &cells[3]);
  const auto dispatch = re_flat_switch32(a, choices[i % 7], &cells[2]);
  const auto straight = re_flat_straight64(a, b);
  const auto unselected = re_flat_unselected32(a, &cells[1]);
  std::printf("%u %08" PRIx32 " %08" PRIx32 " %016" PRIx64 " %08" PRIx32 " %08" PRIx32
      " %08" PRIx32 " %016" PRIx64 " %08" PRIx32 " %08" PRIx32 " %08" PRIx32
      " %08" PRIx32 " %08" PRIx32 "\n", i, branch, loop, phi, memory, recursive,
      dispatch, straight, unselected, cells[0], cells[1], cells[2], cells[3]);
}
int main(int argc, char **argv) {
  if (argc != 1) {
    if (argc != 3 || std::strcmp(argv[1], "--bench") != 0) return 64;
    char *end = nullptr;
    errno = 0;
    const auto rounds = std::strtoull(argv[2], &end, 10);
    if (argv[2][0] == '-' || !rounds || rounds > 1000000000 || errno || *end) return 64;
    std::uint64_t state = UINT64_C(0x5be6918a2c30d47f), checksum = 0;
    std::uint32_t cells[] = {1, 2, 3, 4};
    for (std::uint64_t i = 0; i < rounds; ++i) {
      const auto a = next(state), b = next(state);
      checksum ^= re_flat_branch32(a, b, &cells[0]);
      checksum += re_flat_loop32(a, i, &cells[1]);
      checksum ^= re_flat_phi64(a, b, i, &cells[2]);
      checksum += re_flat_memory32(&cells[0], &cells[i & 1 ? 0 : 3], a, b);
      checksum ^= re_flat_recursive32(a, i % 4, &cells[3]);
    }
    std::printf("%016" PRIx64 "\n", checksum);
    return 0;
  }
  constexpr std::uint64_t edges[] = {0, 1, 2, UINT32_MAX, UINT64_MAX, UINT64_MAX - 1,
      UINT64_C(1) << 31, (UINT64_C(1) << 31) - 1, UINT64_C(1) << 63,
      (UINT64_C(1) << 63) - 1, UINT64_C(0xaaaaaaaa55555555)};
  unsigned i = 0;
  for (auto a : edges) for (auto b : edges) row(i++, a, b);
  std::uint64_t state = UINT64_C(0x5be6918a2c30d47f);
  for (unsigned n = 0; n < 512; ++n) {
    const auto a = next(state), b = next(state);
    row(i++, a, b);
  }
}
