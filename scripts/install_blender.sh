#!/usr/bin/env bash
# Developer/CI helper. Android users never run this script.
set -euo pipefail
runtime_dir="${1:?Usage: scripts/install_blender.sh /absolute/runtime/directory}"
mkdir -p "$runtime_dir"
curl --fail --location --retry 3 --silent --show-error \
  https://download.blender.org/release/Blender4.5/blender-4.5.3-linux-x64.tar.xz \
  -o "$runtime_dir/blender.tar.xz"
printf '%s  %s\n' 975c58fcb244273838534bba771e64ad87739216b0f9b39a888531a49a72d845 "$runtime_dir/blender.tar.xz" | sha256sum --check
tar -xf "$runtime_dir/blender.tar.xz" -C "$runtime_dir"
rm "$runtime_dir/blender.tar.xz"
"$runtime_dir/blender-4.5.3-linux-x64/blender" --version
