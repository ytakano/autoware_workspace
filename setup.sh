#!/usr/bin/bash
git clone https://github.com/autowarefoundation/autoware.git
mkdir -p src 
vcs import src < autoware/repositories/autoware.repos
vcs import src < autoware/repositories/autoware-nightly.repos

rosdep update
rosdep install -y --from-paths src/core --ignore-src --rosdistro humble
