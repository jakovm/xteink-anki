#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "${script_dir}/.." && pwd)"
target="${1:-x4}"
source_override=""

if [[ "${target}" != "x4" && "${target}" != "x4pro" ]]; then
  source_override="${target}"
  target="x4"
elif [[ $# -gt 1 ]]; then
  source_override="$2"
fi

if [[ "${target}" == "x4pro" ]]; then
  build_environment="x4pro-gh_release"
  output_file="${repo_dir}/dist/crosspoint-1.6.5-xteink-anki-x4pro.bin"
else
  build_environment="gh_release"
  output_file="${repo_dir}/dist/crosspoint-1.4.1-xteink-anki.bin"
fi

prepare_source() {
  if [[ "${target}" == "x4pro" ]]; then
    if [[ -n "${source_override}" ]]; then
      "${script_dir}/prepare.sh" --x4pro "${source_override}"
    else
      "${script_dir}/prepare.sh" --x4pro
    fi
  elif [[ -n "${source_override}" ]]; then
    "${script_dir}/prepare.sh" "${source_override}"
  else
    "${script_dir}/prepare.sh"
  fi
}
source_dir="$(prepare_source | tail -n 1)"

# Resolve PlatformIO even when not on PATH (common: ~/.platformio/penv).
platformio_command=()
if command -v pio >/dev/null 2>&1; then
  platformio_command=(pio)
elif command -v platformio >/dev/null 2>&1; then
  platformio_command=(platformio)
elif [[ -x "${HOME}/.platformio/penv/bin/pio" ]]; then
  platformio_command=("${HOME}/.platformio/penv/bin/pio")
elif [[ -x "${HOME}/.platformio/penv/bin/platformio" ]]; then
  platformio_command=("${HOME}/.platformio/penv/bin/platformio")
else
  printf 'PlatformIO/pioarduino was not found in PATH or ~/.platformio/penv/bin.\n' >&2
  exit 1
fi

"${platformio_command[@]}" run --project-dir "${source_dir}" -e "${build_environment}"

# UI_12 (small/large) and UI_18 (native medium) must carry DE/Greek/romanization
# in both weights.
for font_header in \
  "${source_dir}/lib/EpdFont/builtinFonts/ubuntu_12_regular.h" \
  "${source_dir}/lib/EpdFont/builtinFonts/ubuntu_12_bold.h" \
  "${source_dir}/lib/EpdFont/builtinFonts/ubuntu_18_regular.h" \
  "${source_dir}/lib/EpdFont/builtinFonts/ubuntu_18_bold.h"
do
  for required_glyph in U+00DF U+00E4 U+037E U+0387 U+03B1 U+03C9 U+1F00 U+1E53; do
    if ! grep -Fq "${required_glyph}" "${font_header}"; then
      printf 'Required Anki font glyph %s is missing from %s\n' \
        "${required_glyph}" "${font_header}" >&2
      exit 1
    fi
  done
done

install -m 0644 "${source_dir}/.pio/build/${build_environment}/firmware.bin" "${output_file}"

printf 'Firmware: %s\n' "${output_file}"
if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "${output_file}"
fi
