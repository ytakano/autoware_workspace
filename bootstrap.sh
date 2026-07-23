#!/usr/bin/bash
git clone https://github.com/autowarefoundation/autoware.git
mkdir -p src

# Override autoware_core with a fork/branch (method B).
# Rewrites only the url/version lines inside the core/autoware_core: stanza,
# so it stays correct even when upstream bumps the pinned version.
sed -i '/^  core\/autoware_core:/,/^    version:/ {
  s|^\( *url:\).*|\1 https://github.com/ytakano/autoware_core.git|
  s|^\( *version:\).*|\1 ndt_in_rust_3_clean|
}' autoware/repositories/autoware.repos

vcs import src < autoware/repositories/autoware.repos
vcs import src < autoware/repositories/autoware-nightly.repos

rosdep update
rosdep install -y --from-paths src/core --ignore-src --rosdistro humble
