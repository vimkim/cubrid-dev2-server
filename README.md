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
sudo docker build -t local/r8-systemd ./rocky8
```

Both commands build the unversioned Docker image. The roster launcher defaults
to `localhost/local/r8-systemd:250708-ubi-init`. To build that Podman image, run
`just build-rocky8-ubi-init`.

## Run containers

Install [uv](https://docs.astral.sh/uv/) and `just`. Run `just sync` to create
the project-local Python environment from `uv.lock`. The recipes use this
environment without activation or an ambient PyYAML installation.

```bash
just status --json
just plan vimkim1 vimkim2 --json
just apply vimkim1 vimkim2 --json
```

Edit `containers.yaml` before planning a roster change. `status` and `plan`
inspect all configured names by default. Pass exact names to select a subset.
`apply` requires exact names or `--all`. It observes the selection again before
creating any container. `just run-containers` is an alias for `just apply` and
has the same selection requirement. Use `--config PATH` to select another YAML
roster. Run `just` to list the available recipes.

Inspection uses `sudo -n` and rootful Podman. Configure noninteractive sudo
access or authenticate sudo in your terminal before running a live command.
An inspection error stops the command. It does not mean that containers are
missing. Preview commands do not create containers or change accounts.

The JSON output has `schema_version`, `operation`, `source`, and sorted
`containers` fields. States are `missing`, `running`, or `stopped`.
`declaration` compares the stored `spec-hash` label with the YAML entry. A
matching label does not verify the actual image, mounts, account, or SSH access.
`plan` includes the proposed command arguments and provisioning script. Errors
include an `error` object. A mutation failure also reports completed operations
and the failed creation attempt. If `podman run` fails, the partial report marks
creation as `unknown` because Podman can create a container before it fails to
start. Inspect its state before retrying.

Existing containers are preserved whether running, stopped, matching, or
drifted. If account provisioning fails after creation, the container remains.
A later `apply` preserves it and does not retry account setup. Inspect the
reported failure and repair the account manually.

To exercise the planner without Podman, use the included fixture with its
explicit missing and present observations:

```bash
just plan hornetmj1 hornetmj2 hornetmj3 --offline tests/fixtures/inventory.json --json
```

Offline output is labeled `offline` and does not report live state. A fixture
must include every selected name. Offline apply is not available.

Run `just check` for the lock check and CLI behavior tests. The tests use fake
sudo and Podman executables and do not modify host containers. The
`run-vk-ubun24` and `run-centos6-example` recipes are separate one-off image
examples. They do not use the roster workflow.

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

#### ⚠️ Important Warnings

- **Always include your username in the filter** to avoid affecting other users' containers
- The filter supports regular expressions and wildcards due to podman's filtering capabilities
- **DO NOT use broad patterns** like `'.*'` or `'*'` with destructive commands (e.g., `/bin/rm -rf`) as this can damage all matching containers
- Always test with dry-run mode first (default behavior) before using the `-x` flag to execute
- Use caution when executing system-level commands across multiple containers

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
