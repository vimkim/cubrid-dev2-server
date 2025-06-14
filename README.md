## How To Configure?

1. Configure podman network (ipvlan).

You might want to change the IP_RANGE.

```
./podman-network.sh
```

It is known that such network drivers like ipvlan requires rootful podman, therefore you might need `sudo podman`.

2. Build Docker image (r8 with systemd).

```
just build
```

or,

```
sudo docker build -t local/r8-systemd .
```

Both are equivalent.

3. Run containers

```
just run
```

or

```
./run-container.sh
```
