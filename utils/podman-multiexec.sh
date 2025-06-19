#!/bin/bash

# podman-multiexec.sh - Execute shell scripts on multiple podman containers filtered by name

usage() {
    echo "Usage: $0 -f <filter> -s <script> [options]"
    echo ""
    echo "Options:"
    echo "  -f, --filter <filter>    Filter containers by name pattern"
    echo "  -s, --script <script>    Shell script to execute"
    echo "  -v, --verbose           Enable verbose output"
    echo "  -x, --execute           Actually execute the script (default is dry-run)"
    echo "  -h, --help              Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 -f vimkim -s abc.sh                    # Dry run (default)"
    echo "  $0 -f vimkim -s abc.sh --execute          # Actually execute"
    echo "  $0 --filter nginx --script deploy.sh -x   # Execute with short option"
    exit 1
}

# Initialize variables
FILTER=""
SCRIPT=""
VERBOSE=false
EXECUTE=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
    -f | --filter)
        FILTER="$2"
        shift 2
        ;;
    -s | --script)
        SCRIPT="$2"
        shift 2
        ;;
    -v | --verbose)
        VERBOSE=true
        shift
        ;;
    -x | --execute)
        EXECUTE=true
        shift
        ;;
    -h | --help)
        usage
        ;;
    *)
        echo "Unknown option: $1"
        usage
        ;;
    esac
done

# Validate required arguments
if [[ -z "$FILTER" ]]; then
    echo "Error: Filter is required (-f or --filter)"
    usage
fi

if [[ -z "$SCRIPT" ]]; then
    echo "Error: Script is required (-s or --script)"
    usage
fi

# Check if script exists
if [[ ! -f "$SCRIPT" ]]; then
    echo "Error: Script file '$SCRIPT' not found"
    exit 1
fi

# Get container IDs matching the filter
CONTAINER_IDS=$(sudo podman ps --filter name="$FILTER" --format "{{.ID}}")

if [[ -z "$CONTAINER_IDS" ]]; then
    echo "No containers found matching filter: $FILTER"
    exit 1
fi

# Count containers
CONTAINER_COUNT=$(echo "$CONTAINER_IDS" | wc -l)

if [[ "$VERBOSE" == true ]] || [[ "$EXECUTE" == false ]]; then
    echo "Found $CONTAINER_COUNT container(s) matching filter '$FILTER':"
    sudo podman ps --filter name="$FILTER" --format "table {{.ID}}\t{{.Names}}\t{{.Status}}"
    echo ""
fi

# If not executing (dry run by default), show what would be executed and exit
if [[ "$EXECUTE" == false ]]; then
    echo "DRY RUN MODE (default) - This script will execute:"
    echo "Script: $SCRIPT"
    echo "On the following $CONTAINER_COUNT container(s):"
    echo ""

    for container in $CONTAINER_IDS; do
        CONTAINER_NAME=$(sudo podman inspect --format '{{.Name}}' "$container")
        echo "  Container ID: $container"
        echo "  Container Name: $CONTAINER_NAME"
        echo "  Command: sudo podman cp $SCRIPT $container:/tmp/$(basename "$SCRIPT")"
        echo "  Command: sudo podman exec $container bash -c \"chmod +x /tmp/$(basename "$SCRIPT") && /tmp/$(basename "$SCRIPT")\""
        echo ""
    done

    echo "Use --execute or -x to actually run the script."
    exit 0
fi

echo "Executing script '$SCRIPT' on $CONTAINER_COUNT container(s)..."
echo ""

# Execute script on each container
SUCCESS_COUNT=0
FAILED_COUNT=0

for container in $CONTAINER_IDS; do
    CONTAINER_NAME=$(sudo podman inspect --format '{{.Name}}' "$container")

    if [[ "$VERBOSE" == true ]]; then
        echo "Processing container: $container ($CONTAINER_NAME)"
    else
        echo "Processing: $CONTAINER_NAME"
    fi

    # Copy script to container
    if sudo podman cp "$SCRIPT" "$container:/tmp/$(basename "$SCRIPT")" 2>/dev/null; then
        # Execute script
        if sudo podman exec "$container" bash -c "chmod +x /tmp/$(basename "$SCRIPT") && /tmp/$(basename "$SCRIPT")" 2>/dev/null; then
            echo "  ✓ Success"
            ((SUCCESS_COUNT++))
        else
            echo "  ✗ Failed to execute script"
            ((FAILED_COUNT++))
        fi
    else
        echo "  ✗ Failed to copy script"
        ((FAILED_COUNT++))
    fi

    if [[ "$VERBOSE" == true ]]; then
        echo ""
    fi
done

echo ""
echo "Summary:"
echo "  Total containers: $CONTAINER_COUNT"
echo "  Successful: $SUCCESS_COUNT"
echo "  Failed: $FAILED_COUNT"

if [[ $FAILED_COUNT -gt 0 ]]; then
    exit 1
fi
