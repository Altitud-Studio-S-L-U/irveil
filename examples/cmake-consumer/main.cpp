#include <irveil/Protect.h>

#include <cerrno>
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

extern "C" IRVEIL_PROTECT std::uint32_t
protected_calculation(std::uint32_t a, std::uint32_t b) {
  std::uint32_t value = a + b;
  value ^= a >> 3;
  value += b ^ UINT32_C(0xa5a5a5a5);
  value ^= b >> 7;
  return value + (a ^ UINT32_C(0x13579bdf));
}

extern "C" __attribute__((noinline)) std::uint32_t
ordinary_calculation(std::uint32_t a, std::uint32_t b) {
  std::uint32_t value = a + b;
  value ^= a >> 3;
  value += b ^ UINT32_C(0xa5a5a5a5);
  value ^= b >> 7;
  return value + (a ^ UINT32_C(0x13579bdf));
}

static bool parse(const char *text, std::uint32_t &value) {
  if (*text == '\0')
    return false;
  for (const char *cursor = text; *cursor; ++cursor)
    if (*cursor < '0' || *cursor > '9')
      return false;
  errno = 0;
  char *end = nullptr;
  const auto parsed = std::strtoull(text, &end, 10);
  if (errno != 0 || *end != '\0' || parsed > UINT32_MAX)
    return false;
  value = static_cast<std::uint32_t>(parsed);
  return true;
}

int main(int argc, char **argv) {
  std::uint32_t a = UINT32_C(123456789);
  std::uint32_t b = UINT32_C(987654321);
  if ((argc != 1 && argc != 3) ||
      (argc == 3 && (!parse(argv[1], a) || !parse(argv[2], b)))) {
    std::fprintf(stderr, "usage: %s [a b], unsigned decimal values 0..4294967295\n", argv[0]);
    return 1;
  }
  const auto selected = protected_calculation(a, b);
  const auto ordinary = ordinary_calculation(a, b);
  std::printf("protected=%" PRIu32 " ordinary=%" PRIu32 "\n", selected, ordinary);
  return selected == ordinary ? 0 : 1;
}
