# Autoware Core Development Environment

## Use Docker

First, build a docker image and attach the docker container as follows.

```
$ cd docker
$ sh build.sh
$ sh up_docker.sh
$ sh exec_zsh.sh
```

## Build Autoware Core in the Docker 

```
user@autoware %> ./bootstrap.sh
user@autoware %> ./build.sh
```

## Run Tests

`./test.sh` runs `colcon test` for the packages under `src/core` and prints a
result summary. It forwards any extra arguments to `colcon test`.

```
user@autoware %> ./test.sh                                   # all tests under src/core
user@autoware %> ./test.sh --packages-select autoware_ndt_scan_matcher
user@autoware %> ./test.sh --packages-select autoware_ndt_scan_matcher \
                           --ctest-args -R test_estimate_covariance
```

Note: a bare `./test.sh` also runs the slow integration/launch tests
(300s timeouts, PCD maps required). Filter with `--packages-select` /
`--ctest-args -R` for quick iteration.

