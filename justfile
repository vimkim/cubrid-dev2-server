build:
    sudo docker build -t local/r8-systemd .

run:
    ./run-container.sh

run-containers:
    python run_dev_containers.py
