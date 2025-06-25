# Use Ubuntu as base image
FROM ubuntu:latest

# Install necessary packages including SSH server
RUN apt update -y && apt upgrade -y && \
    apt install -y \
        sudo \
        gdb \
        openssh-server \
        which \
        vim \
        git \
        gcc \
        make \
        g++ \
        cmake \
        ninja-build \
        openjdk-8-jdk \
        flex \
        bison \
        ncurses-dev \
        systemtap-sdt-dev \
        libelf-dev \
        build-essential && \
    apt clean && rm -rf /var/lib/apt/lists/*

# Create user 'vimkim' with sudo access
RUN useradd -m -s /bin/bash vimkim && \
    echo "vimkim ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers && \
    echo 'vimkim:password' | chpasswd

RUN mkdir -p /run/sshd && \
    sed -i 's/#X11Forwarding no/X11Forwarding yes/' /etc/ssh/sshd_config && \
    echo 'X11UseLocalhost no' >> /etc/ssh/sshd_config && \
    echo 'PermitRootLogin no' >> /etc/ssh/sshd_config && \
    echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config

# Ensure SSH host keys are generated
RUN ssh-keygen -A

# Expose SSH port
EXPOSE 22

# Set default working directory
WORKDIR /home/vimkim

# Ensure SSH host keys exist before starting SSHD
ENTRYPOINT ["/bin/bash", "-c", "test -f /etc/ssh/ssh_host_rsa_key || ssh-keygen -A && exec /usr/sbin/sshd -D"]
