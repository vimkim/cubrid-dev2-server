# How To Configure?

## Configure podman network (ipvlan)

You might want to change the IP_RANGE.

```bash
./podman-network.sh
```

It is known that such network drivers like ipvlan requires rootful podman,
therefore you might need `sudo podman`.

## Build Docker image (r8 with systemd)

```bash
just build
```

or,

```bash
sudo docker build -t local/r8-systemd .
```

Both are equivalent.

## Run containers

Edit containers.yaml file, and run

```bash
python run_dev_containers.py
```
