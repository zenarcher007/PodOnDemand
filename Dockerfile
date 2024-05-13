FROM alpine

RUN apk update && apk add bash openssh-server openssh python3 python3-dev gcc py3-pip musl-dev ethtool linux-headers shadow openssl
#RUN adduser -D login; echo 'login:' | chpasswd # Empty password (i.e. users can log in to the user without specifying a password (old method))
RUN adduser -D login
# Lock the "login" account - users will no longer log into this.
RUN passwd -l login

# Fix ssh bugs
RUN mkdir /run/sshd
RUN cd /etc/ssh && ssh-keygen -A

ENV HOME=/home/login
WORKDIR $HOME
USER login

RUN python3 -m pip install --break-system-packages kubernetes psutil regex argparse

# Install login scripts
COPY --chown=root sshd_config /etc/ssh/sshd_config
COPY --chown=login login.sh login.sh
#COPY --chown=login startuserpod.py startuserpod.py
#COPY --chown=login stopuserpod.py stopuserpod.py
COPY --chown=login garbagecollectd.py garbagecollectd.py
COPY --chown=login keyimportd.py keyimportd.py
COPY --chown=login run_pod.py run_pod.py

RUN mkdir logs

RUN chmod +x login.sh run_pod.py garbagecollectd.py keyimportd.py
#startuserpod.py stopuserpod.py

USER root
RUN addgroup loginjail
RUN usermod -aG loginjail login

ENTRYPOINT /usr/bin/env > /var/run/startup_environment && ./garbagecollectd.py && ./keyimportd.py && /usr/sbin/sshd -D -e 2>&1 | tee "/home/login/logs/perpod/$HOSTNAME" | awk '{ print strftime("%Y %b %d - %r: "), $0; fflush(); }'