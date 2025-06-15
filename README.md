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

## Q & A

### ❓ Why is the Docker image so large and why are there so many layers? 2 GB?

**💬 Answer:**

The Dockerfile is intentionally structured with many layers and a larger final image size **not to optimize for the minimal image size**, but to **optimize for faster iterative development and rebuild times**.

During development, we prioritize **build efficiency** over the final image size. By keeping more layers and structuring the Dockerfile to maximize the use of Docker's layer cache, we can:

- Avoid redoing expensive steps when only a small part of the code or configuration changes
- Reuse previous build artifacts as much as possible
- Speed up feedback cycles and local testing
- Improve CI performance when caching is available

This trade-off is intentional and helps improve developer productivity and iteration speed.

If a smaller image is desired for production deployment, a separate, more optimized Dockerfile (e.g., using multi-stage builds or distroless images) can be used.
