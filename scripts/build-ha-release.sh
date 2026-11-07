#!/usr/bin/env bash
# Build a manually installable Home Assistant custom-component release archive.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-"${project_dir}/dist"}"
version="$(sed -n 's/^version = "\([^"]*\)"$/\1/p' "${project_dir}/pyproject.toml" | head -n 1)"

if [[ -z "${version}" ]]; then
  echo "Could not determine the project version" >&2
  exit 1
fi

mkdir -p "${output_dir}"
staging_dir="$(mktemp -d)"
trap 'rm -rf "${staging_dir}"' EXIT

component_dir="${staging_dir}/custom_components/dmac"
mkdir -p "${component_dir}"
cp -R "${project_dir}/custom_components/dmac/." "${component_dir}/"
cp -R "${project_dir}/dm_accounting" "${component_dir}/dm_accounting"
cp -R "${project_dir}/ha_adapter" "${component_dir}/ha_adapter"
find "${staging_dir}" -type d -name '__pycache__' -prune -exec rm -rf {} +

archive_path="${output_dir}/dmac-${version}.zip"
rm -f "${archive_path}"
(
  cd "${staging_dir}"
  zip -qr "${archive_path}" custom_components
)

echo "Built ${archive_path}"
