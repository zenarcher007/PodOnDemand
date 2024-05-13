FROM nvidia/cuda:12.0.0-cudnn8-devel-ubuntu22.04
#FROM nvidia/cuda:11.3.1-cudnn8-devel-ubuntu20.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt update -y && apt install -y openssh-server python3-pip openssl vim nano emacs sudo g++ gdb make
###RUN python3 -m pip install --no-cache numpy torch
# Install cuda stuff
###RUN apt install -y nvidia-cuda-gdb 
# Install user stuff
RUN apt install -y git
#cuda

COPY sshd_config /etc/ssh/sshd_config

# Change the root password   V password here
RUN usermod --password "$(echo -n pod | openssl passwd -1 -stdin)" root

# Fix missing privilege separation directory
RUN mkdir /run/sshd

# Copy entry script for dynamically adding user
COPY cuda/entry.sh /var/run/entry.sh
COPY ../motd /etc
RUN chmod +x /var/run/entry.sh

COPY cuda/default-bashrc /usr/default-bashrc
COPY default-bash_profile /usr/default-bash_profile

#tensorflow

ENTRYPOINT ["/var/run/entry.sh"]

