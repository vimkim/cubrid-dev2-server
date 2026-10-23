### how to run container?

```bash
just run-centos6-example
```

This recipe uses `examples/centos6.yaml` and the reviewed resource policy.
Read [the policy and migration procedure](../docs/resource-policy.md) before deployment.

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
