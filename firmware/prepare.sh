#!/usr/bin/env bash
set -euo pipefail

readonly X4_CROSSPOINT_VERSION="1.4.1"
readonly X4_CROSSPOINT_COMMIT="970b2c6ca13d663eff1bcee9778dc48359d2ab70"
readonly X4PRO_CROSSPOINT_VERSION="1.6.5"
readonly X4PRO_CROSSPOINT_COMMIT="93e98bb78702e29868a16a13b80c40e6b36ccdff"
readonly CROSSPOINT_REPOSITORY="https://github.com/crosspoint-reader/crosspoint-reader.git"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "${script_dir}/.." && pwd)"
profile="x4"
crosspoint_version="${X4_CROSSPOINT_VERSION}"
crosspoint_commit="${X4_CROSSPOINT_COMMIT}"
patch_file="${script_dir}/patches/crosspoint-1.4.1-anki.patch"

if [[ "${1:-}" == "--x4pro" ]]; then
  profile="x4pro"
  crosspoint_version="${X4PRO_CROSSPOINT_VERSION}"
  crosspoint_commit="${X4PRO_CROSSPOINT_COMMIT}"
  patch_file="${script_dir}/patches/crosspoint-1.6.5-anki.patch"
  shift
fi

if [[ $# -gt 0 ]]; then
  source_dir="$1"
else
  if command -v shasum >/dev/null 2>&1; then
    patch_hash="$(shasum -a 256 "${patch_file}" | awk '{print $1}')"
  else
    patch_hash="$(sha256sum "${patch_file}" | awk '{print $1}')"
  fi
  source_dir="${repo_dir}/.firmware-build/crosspoint-reader-${crosspoint_version}"
  if [[ "${profile}" == "x4pro" ]]; then
    source_dir+="-x4pro"
  fi
  source_dir+="-${patch_hash:0:12}"
fi

if [[ ! -d "${source_dir}/.git" ]]; then
  mkdir -p "$(dirname "${source_dir}")"
  git clone \
    --branch "${crosspoint_version}" \
    --depth 1 \
    --recurse-submodules \
    "${CROSSPOINT_REPOSITORY}" \
    "${source_dir}"
fi

actual_commit="$(git -C "${source_dir}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${crosspoint_commit}" ]]; then
  printf 'Expected CrossPoint %s at %s, found %s\n' \
    "${crosspoint_version}" "${crosspoint_commit}" "${actual_commit}" >&2
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
