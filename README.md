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

## Utility Scripts

### podman-multiexec.sh

In order to execute a script in multiple containers that match a specific filter, you can use the `podman-multiexec.sh` utility script.

```bash
Usage: ./utils/podman-multiexec.sh -f <filter> -s <script> [options]

Options:
  -f, --filter <filter>    Filter containers by name pattern
  -s, --script <script>    Shell script to execute
  -v, --verbose           Enable verbose output
  -x, --execute           Actually execute the script (default is dry-run)
  -h, --help              Show this help message

Examples:
  ./utils/podman-multiexec.sh -f vimkim -s abc.sh                    # Dry run (default)
  ./utils/podman-multiexec.sh -f vimkim -s abc.sh --execute          # Actually execute
  ./utils/podman-multiexec.sh -f nginx -s abc.sh -x                  # Actually execute
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

### IP address already in use

Once I recraeted the ipvlan network, and create a container with the previously used IP address, I got the following error:

```
IP address already in use ...
```

Solution is the following. Caution: this will stop all podman processes and clear the network cache. Know what you are doing.

```bash
# Restart network namespace
sudo ip netns list  # check for any leftover namespaces
sudo ip netns delete <namespace_name>  # if any exist

# Reload netowrk modules
sudo systemctl restart NetworkManager
sudo systemctl restart systemd-networkd
```

```bash
# Stop all podman processes
sudo pkill -f podman
sudo pkill -f conmon
```

Clear any remaining network cache.

```bash
# Flush route cache
sudo ip route flush cache

# Clear ARP/neighbor cache
sudo ip neigh flush all
```
