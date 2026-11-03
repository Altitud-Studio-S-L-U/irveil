#include <array>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <random>

extern "C" std::uint32_t add32(std::uint32_t, std::uint32_t);
extern "C" std::uint64_t add64(std::uint64_t, std::uint64_t);
extern "C" std::int32_t signed32(std::int32_t, std::int32_t);
extern "C" std::int64_t signed64(std::int64_t, std::int64_t);
extern "C" std::uint32_t unsigned32(std::uint32_t, std::uint32_t);
extern "C" std::uint64_t unsigned64(std::uint64_t, std::uint64_t);

int main() {
  constexpr std::array<std::uint64_t, 8> boundaries = {
      0, 1, 2, UINT64_MAX, UINT64_MAX - 1, UINT64_C(1) << 63,
      (UINT64_C(1) << 63) - 1, UINT64_C(0xaaaaaaaa55555555)};
  std::uint64_t checked = 0;
  for (auto a : boundaries) {
    for (auto b : boundaries) {
      const auto a32 = static_cast<std::uint32_t>(a);
      const auto b32 = static_cast<std::uint32_t>(b);
      if (add64(a, b) != a + b || add32(a32, b32) != a32 + b32)
        return 1;
      checked += 2;
    }
  }
  constexpr std::array<std::int64_t, 4> signed64_edges = {
      INT64_MIN, INT64_MAX, -1, 0};
  for (auto a : signed64_edges) {
    if (signed64(a, 0) != a || signed64(0, a) != a)
      return 2;
    checked += 2;
  }
  constexpr std::array<std::int32_t, 4> signed32_edges = {
      INT32_MIN, INT32_MAX, -1, 0};
  for (auto a : signed32_edges) {
    if (signed32(a, 0) != a || signed32(0, a) != a)
      return 3;
    checked += 2;
  }
  if (unsigned64(UINT64_MAX - 1, 1) != UINT64_MAX ||
      unsigned32(UINT32_MAX - 1, 1) != UINT32_MAX)
    return 4;
  checked += 2;
  std::mt19937_64 random(UINT64_C(0x409c7e316bd2a5f8));
  for (unsigned iteration = 0; iteration < 50'000; ++iteration) {
    const auto a = random();
    const auto b = random();
    const auto a32 = static_cast<std::uint32_t>(a);
    const auto b32 = static_cast<std::uint32_t>(b);
    if (add64(a, b) != a + b || add32(a32, b32) != a32 + b32)
      return 5;
    const auto sa = static_cast<std::int64_t>(a % (UINT64_C(1) << 40)) -
                    (INT64_C(1) << 39);
    const auto sb = static_cast<std::int64_t>(b % (UINT64_C(1) << 40)) -
                    (INT64_C(1) << 39);
    const auto sa32 = static_cast<std::int32_t>(a % (UINT64_C(1) << 28)) -
                      (INT32_C(1) << 27);
    const auto sb32 = static_cast<std::int32_t>(b % (UINT64_C(1) << 28)) -
                      (INT32_C(1) << 27);
    if (signed64(sa, sb) != sa + sb || signed32(sa32, sb32) != sa32 + sb32)
      return 6;
    const auto ua = a >> 1;
    const auto ub = b >> 1;
    const auto ua32 = a32 >> 1;
    const auto ub32 = b32 >> 1;
    if (unsigned64(ua, ub) != ua + ub ||
        unsigned32(ua32, ub32) != ua32 + ub32)
      return 7;
    checked += 6;
  }
  std::printf("checked=%llu\n", static_cast<unsigned long long>(checked));
  return 0;
}
