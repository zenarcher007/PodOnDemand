#!/usr/bin/env bash

set -e

USER="$1"
ENCRYPTED_PASS="$2"
PUBLIC_KEY="$3"

if [[ -z "$USER" ]]; then
  USER="knoxuser"
fi

adduser --disabled-password --no-create-home --gecos '' "$USER" # Home directory will be mounted automatically by PodOnDemand
# Set user password. Password can be empty
#usermod --password $(openssl passwd -1 -stdin <<< "knox") "$USER"
usermod --password "$ENCRYPTED_PASS" "$USER"
usermod --password "$ENCRYPTED_PASS" root
usermod -aG sudo "$USER"

chown "$USER:$USER" "/home/$USER" # Allow new user access to volume

# The argument passed in for "PASS" is currently actually a base64-encoded authorized_keys file entry. Install this in the
# user's home directory (this will be, consequently, inside the persistent volume, but this will also allow users
# to store their own private keys as needed for projects or something)
if ! [[ -z "$PUBLIC_KEY" ]]; then
  if ! [[ -d "/home/$USER/.ssh" ]]; then
    mkdir "/home/$USER/.ssh"
    chmod 755 "/home/$USER/.ssh"
    chown "$USER:$USER" "/home/$USER/.ssh"
  fi
  if ! [[ -f "/home/$USER/.ssh/authorized_keys" ]]; then
    touch "/home/$USER/.ssh/authorized_keys"
    chmod 600 "/home/$USER/.ssh/authorized_keys"
    chown "$USER:$USER" "/home/$USER/.ssh/authorized_keys"
  fi
  base64 -d <<< "$PUBLIC_KEY" > "/home/$USER/.ssh/authorized_keys"
  # Add newline
  echo >> "/home/$USER/.ssh/authorized_keys"
fi

if ! [[ -f "/home/$USER/.bashrc" ]]; then
  mv /usr/default-bashrc "/home/$USER/.bashrc"
  chown "$USER:$USER" "/home/$USER/.bashrc"
fi
if ! [[ -f "/home/$USER/.bash_profile" ]]; then
  mv /usr/default-bash_profile "/home/$USER/.bash_profile"
  chown "$USER:$USER" "/home/$USER/.bash_profile"
fi

usermod --shell /bin/bash "$USER"

/usr/sbin/sshd -D -e # Run sshd daemon