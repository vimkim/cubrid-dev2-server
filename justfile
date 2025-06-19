build:
    sudo docker build -t local/r8-systemd ./rocky8

run:
    ./run-container.sh

run-containers:
    python run_dev_containers.py
