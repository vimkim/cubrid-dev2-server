### how to run container?

```bash
sudo podman run -d --name chijun0 --network dev2-net --ip 192.168.4.160 --hostname chijun0 --privileged -v vol-chijun0:/home localhost/cubridci:latest tail -f /dev/null
```

#### How to set up sshd?

```bash
yum install -y openssh-server
sudo ssh-keygen -t rsa -f /etc/ssh/ssh_host_rsa_key -N ''
sudo ssh-keygen -t dsa -f /etc/ssh/ssh_host_dsa_key -N ''
/usr/sbin/sshd # for non systemd containers, you need to run sshd manually
```

#### how to ssh into it?

```bash
ssh -oHostKeyAlgorithms=+ssh-rsa,ssh-dss hornetmj@192.168.4.100
```

Centos 6 is EOL, so you need to use `-oHostKeyAlgorithms=+ssh-rsa,ssh-dss` to connect to it.
