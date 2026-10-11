#!/usr/bin/env bash
set -euo pipefail

readonly CROSSPOINT_VERSION="1.6.5"
readonly CROSSPOINT_COMMIT="93e98bb78702e29868a16a13b80c40e6b36ccdff"
readonly CROSSPOINT_REPOSITORY="https://github.com/crosspoint-reader/crosspoint-reader.git"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "${script_dir}/.." && pwd)"
patch_file="${script_dir}/patches/crosspoint-1.6.5-anki.patch"

if [[ $# -gt 0 ]]; then
  source_dir="$1"
else
  if command -v shasum >/dev/null 2>&1; then
    patch_hash="$(shasum -a 256 "${patch_file}" | awk '{print $1}')"
  else
    patch_hash="$(sha256sum "${patch_file}" | awk '{print $1}')"
  fi
  source_dir="${repo_dir}/.firmware-build/crosspoint-reader-${CROSSPOINT_VERSION}-${patch_hash:0:12}"
fi

if [[ ! -d "${source_dir}/.git" ]]; then
  mkdir -p "$(dirname "${source_dir}")"
  git clone \
    --branch "${CROSSPOINT_VERSION}" \
    --depth 1 \
    --recurse-submodules \
    "${CROSSPOINT_REPOSITORY}" \
    "${source_dir}"
fi

actual_commit="$(git -C "${source_dir}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${CROSSPOINT_COMMIT}" ]]; then
  printf 'Expected CrossPoint %s at %s, found %s\n' \
    "${CROSSPOINT_VERSION}" "${CROSSPOINT_COMMIT}" "${actual_commit}" >&2
  exit 1
fi

git -C "${source_dir}" submodule update --init --recursive

if git -C "${source_dir}" apply --reverse --check "${patch_file}" >/dev/null 2>&1; then
  printf 'Anki firmware patch is already applied in %s\n' "${source_dir}"
elif git -C "${source_dir}" apply --check "${patch_file}"; then
  git -C "${source_dir}" apply "${patch_file}"
  printf 'Applied Anki firmware patch in %s\n' "${source_dir}"
else
  printf 'The CrossPoint checkout contains changes that conflict with the Anki patch: %s\n' \
    "${source_dir}" >&2
  exit 1
fi

printf '%s\n' "${source_dir}"
