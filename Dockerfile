# ──────────────────────────────────────────────────────────────
# Rocky 8.10 + systemd + OpenSSH + basic dev tooling
# ──────────────────────────────────────────────────────────────
FROM quay.io/rockylinux/rockylinux:8.10

ENV container docker               # lets systemd know it’s in a container

RUN (cd /lib/systemd/system/sysinit.target.wants; \
       for i in *; do [ "$i" = systemd-tmpfiles-setup.service ] || rm -f "$i"; done) && \
    rm -f /lib/systemd/system/multi-user.target.wants/* \
          /etc/systemd/system/*.wants/* \
          /lib/systemd/system/local-fs.target.wants/* \
          /lib/systemd/system/sockets.target.wants/*udev* \
          /lib/systemd/system/sockets.target.wants/*initctl* \
          /lib/systemd/system/basic.target.wants/* \
          /lib/systemd/system/anaconda.target.wants/*

# ---- install OpenSSH, sudo and common dev tools -------------------------------
RUN dnf -y update && dnf -y install epel-release

RUN dnf -y install \
        openssh-server sudo which git vim-enhanced less \
        @'Development Tools' \
        htop

RUN dnf -y --enablerepo=powertools install libstdc++-static ninja-build
RUN dnf -y install cmake \
        systemtap-devel \
        systemtap-sdt-devel \
        ncurses-devel \
        java-1.8.0-openjdk-devel \
        perl

RUN dnf clean all

# 1) add dev user
RUN useradd -m -s /bin/bash dev \
 && echo 'dev:changeme'  | chpasswd \
 && usermod -aG wheel dev

RUN echo '%wheel ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/99-wheel \
 && chmod 0440 /etc/sudoers.d/99-wheel

# 2) set a root password
RUN echo 'root:changeme' | chpasswd

# ---- relax sshd policy so passwords are accepted ----------------------------
RUN set -eux; \
    # enable password logins in general
    sed -ri 's/^#?PasswordAuthentication .*/PasswordAuthentication yes/' \
        /etc/ssh/sshd_config; \
    # explicitly permit root over SSH (default in Rocky is “prohibit-password”)
    sed -ri 's/^#?PermitRootLogin .*/PermitRootLogin yes/' \
        /etc/ssh/sshd_config; \
    # make sure PAM stays on (needed for password auth)
    sed -ri 's/^#?UsePAM .*/UsePAM yes/' /etc/ssh/sshd_config

# ---- prepare sshd -------------------------------------------------------------
RUN mkdir -p /var/run/sshd \
    && ssh-keygen -A                    # generate host keys

# ---- enable the needed systemd units -----------------------------------------
RUN systemctl enable sshd


# ---- remove 'Unprivileged users are not permitted to log in'
RUN rm -rf /run/nologin

USER dev
WORKDIR /home/dev

VOLUME ["/sys/fs/cgroup"]
EXPOSE 22
CMD ["/usr/sbin/init"]
