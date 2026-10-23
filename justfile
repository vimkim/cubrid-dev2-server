python := env_var_or_default("DEV2_PYTHON", "/usr/bin/python3")

build:
    sudo docker build -t local/r8-systemd ./rocky8

build-rocky8-ubi-init:
    sudo podman build --format=docker -t local/r8-systemd:250708-ubi-init ./rocky8

run:
    "{{python}}" run_dev_containers.py

run-containers:
    "{{python}}" run_dev_containers.py

build-ubuntu24:
    sudo podman build -t localhost/cubrid-ubuntu24:latest ./ubuntu24/

run-vk-ubun24:
    "{{python}}" run_dev_containers.py --config examples/ubuntu24.yaml --only vk-ubun24

run-centos6-example:
    "{{python}}" run_dev_containers.py --config examples/centos6.yaml --only chijun0
