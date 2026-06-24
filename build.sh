#!/usr/bin/bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install --base-paths src/core --cmake-args -DCMAKE_BUILD_TYPE=Release
