FROM ubuntu

RUN apt update -y && apt install -y openssh-server openssl vim nano emacs sudo git g++ gdb make
COPY sshd_config /etc/ssh/sshd_config

# Change the root password   V password here
RUN usermod --password "$(echo -n pod | openssl passwd -1 -stdin)" root

# Fix missing privilege separation directory
RUN mkdir /run/sshd

# Copy entry script for dynamically adding user
COPY cpu/entry.sh /var/run/entry.sh
COPY motd /etc/
RUN chmod +x /var/run/entry.sh

COPY cpu/default-bashrc /usr/default-bashrc
COPY default-bash_profile /usr/default-bash_profile

RUN mkdir -p /tmp/outputs

ENTRYPOINT ["/var/run/entry.sh"]

