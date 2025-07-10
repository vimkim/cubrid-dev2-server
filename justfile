build:
    sudo docker build -t local/r8-systemd ./rocky8

build-rocky8-ubi-init:
    sudo podman build --format=docker -t local/r8-systemd:250708-ubi-init ./rocky8

run:
    ./run-container.sh

run-containers:
    python run_dev_containers.py

build-ubuntu24:
    sudo podman build -t localhost/cubrid-ubuntu24:latest ./ubuntu24/

run-vk-ubun24:
    sudo podman run -d --name vk-ubun24 --network dev2-net --ip 192.168.4.159 --hostname vk-ubun24 --privileged -v "vol-vk-ubun24:/home" localhost/cubrid-ubuntu24:latest
