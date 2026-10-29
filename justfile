set positional-arguments

default:
    @just --list

sync:
    uv sync --locked --project "{{justfile_directory()}}"

test:
    uv run --locked --project "{{justfile_directory()}}" python -m unittest discover -s "{{justfile_directory()}}/tests" -v

check:
    uv lock --check --project "{{justfile_directory()}}"
    uv run --locked --project "{{justfile_directory()}}" python -m unittest discover -s "{{justfile_directory()}}/tests" -v

status *args:
    @uv run --locked --project "{{justfile_directory()}}" python "{{justfile_directory()}}/run_dev_containers.py" status "$@"

plan *args:
    @uv run --locked --project "{{justfile_directory()}}" python "{{justfile_directory()}}/run_dev_containers.py" plan "$@"

apply *args:
    @uv run --locked --project "{{justfile_directory()}}" python "{{justfile_directory()}}/run_dev_containers.py" apply "$@"

run-containers *args:
    @uv run --locked --project "{{justfile_directory()}}" python "{{justfile_directory()}}/run_dev_containers.py" apply "$@"

build:
    sudo docker build -t local/r8-systemd ./rocky8

build-rocky8-ubi-init:
    sudo podman build --format=docker -t local/r8-systemd:250708-ubi-init ./rocky8

build-ubuntu24:
    sudo podman build -t localhost/cubrid-ubuntu24:latest ./ubuntu24/

run-vk-ubun24:
    sudo podman run -d --name vk-ubun24 --network dev2-net --ip 192.168.4.159 --hostname vk-ubun24 --privileged -v "vol-vk-ubun24:/home" localhost/cubrid-ubuntu24:latest

run-centos6-example:
    sudo podman run -d --name chijun0 --network dev2-net --ip 192.168.4.160 --hostname chijun0 --privileged -v vol-chijun0:/home localhost/cubridci:latest tail -f /dev/null
