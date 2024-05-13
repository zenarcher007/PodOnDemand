#!/usr/bin/env python3
import sys
import os
import datetime
import traceback
import time
import subprocess
import regex as re
import shutil
import uuid

# Adapted from https://gist.github.com/Jd007/5573672
# Forks the process and detaches ownership from the shell process to continue in background
# You may specify the stdin, stdout, and stderr paths for logging / input
def daemonize(stdout: str, stderr: str, stdin: str = None):
  try:
    pid = os.fork()
    if pid > 0:
      # Exit from first parent
      sys.exit(0)
  except OSError as e:
    sys.stderr.write("Fork #1 failed: " + str(e))
    sys.exit(1)

  # Decouple from parent environment
  os.chdir("/")
  os.setsid()
  os.umask(0)

  # Second fork
  try:
    pid = os.fork()
    if pid > 0:
      # Exit from second parent
      sys.exit(0)
  except OSError as e:
    sys.stderr.write("Fork #2 failed: " + str(e))
    sys.exit(1)
  
  sys.stdout.flush()
  sys.stderr.flush()
  if stdin != None:
    with open(stdin, 'r') as si:
      os.dup2(si.fileno(), sys.stdin.fileno())
  with open(stdout, 'a+') as so:
    os.dup2(so.fileno(), sys.stdout.fileno())
  with open(stderr, 'a+') as se:
    os.dup2(se.fileno(), sys.stderr.fileno())


# Monitors ~/.ssh/authorized_keys, and adds users present in the file, or deletes users not present.
def main(argv):
  sshdir = os.path.expanduser("~/.ssh")
  authorized_keys = sshdir + "/authorized_keys"
  
  if not os.path.isfile(authorized_keys):
    # Panic and exit - key importer will be disabled because .ssh dir was not mounted with authorized_keys at runtime
    print(datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y"))
    print(f"{argv[0]}: Error: {sshdir}/authorized_keys does not exist (is the volume mounted)? Key importer will be DISABLED! Exiting...")
    sys.exit(0)
  
  print("Starting keyimportd on " + str(datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y")))
  #daemonize(sys.stdout, sys.stderr, sys.stdin)
  daemonize(stdout = os.getenv("HOME") + "/logs/keyimportd_out.log", stderr = os.getenv("HOME") + "/logs/keyimportd_err.log")
  oldmtime = None
  while True:
    try:
      while True:
        mtime = os.path.getmtime(authorized_keys)
        if oldmtime != mtime:
          oldmtime = mtime

          # All users in authorized_keys file
          ku_set = set()

          # Parse and read authorized_keys into ku_set, and fill user_to_key_line
          user_to_key_line = {}
          with open(authorized_keys, 'r') as keys:
            for line in keys:
              if not line or line == '\n' or line.startswith('#'):
                continue
              line = re.search(r'ssh-.* AAAA.*$', line).group(0) # Get the key after any command= param
              try:
                username = re.search(r'(?<= )[A-Za-z0-9-_]+(?=@)', line)
                if username is None:
                  username = re.search(r'(?<= )[A-Za-z0-9-_]+(?=$)', line)
                username = username.group(0)
                if username in ku_set:
                  # I want to get your attention.
                  print(datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y"), file = sys.stdout)
                  print(datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y"), file = sys.stderr)
                  msg = f"WARNING: DUPLICATE USER \"{username}\" FOUND! PLEASE CONSIDER RENAMING THIS USER! No changes made."
                  print(msg, file = sys.stdout)
                  print(msg, file = sys.stderr)
                ku_set.add(username)
                user_to_key_line[username] = line
              except Exception as e:
                if isinstance(e, KeyboardInterrupt):
                  raise e
                print(datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y"))
                traceback.print_tb(e.__traceback__)
                print(f"Exception on line \"{line}\" of key file: {str(e)}")
          
          

          #sys_users_proc = subprocess.run(['getent', 'passwd'], capture_output=True) # All users currently in PodOnDemand container
          #system_users = list(re.findall(r'^[A-Za-z0-9-_]+(?=:)', sys_users_proc.stdout.decode('UTF-8'))
          system_users = os.listdir('/home')
          system_users.remove('login')
          su_set = set(system_users)
          
          # Add all users in key file not currently present on system
          for user in ku_set:
            if not user in su_set:
              try:
                try:
                  print(f"Adding new system user {user}...")
                  subprocess.run(['adduser', '--disabled-password', '--gecos', '', user], check=True) # https://askubuntu.com/questions/94060/run-adduser-non-interactively
                  subprocess.run(['usermod', '-aG', 'loginjail', user], check=True)
                  #subprocess.run(['usermod', '-p', '*', user], check=True) # Disable password for this user
                  #subprocess.run(['sh', '-c' 'echo "{user}:{str(uuid.uuid4())}" | chpasswd -e'], check=True)
                  subprocess.run(['usermod', '-p', '*', user], check=True)
                  os.mkdir(f"/home/{user}/ssh")
                  os.chmod(f"/home/{user}/ssh", 0o755)
                  shutil.chown(f"/home/{user}/ssh", user=user, group=user)
                  with open(f"/home/{user}/ssh/authorized_keys", 'w') as userkeyfile:
                    keyline = user_to_key_line[user]
                    userkeyfile.write(keyline)
                  os.chmod(f"/home/{user}/ssh/authorized_keys", 0o600)
                  shutil.chown(f"/home/{user}/ssh/authorized_keys", user=user, group=user)
                  os.rename(f"/home/{user}/ssh", f"/home/{user}/.ssh") # Make it so the .ssh directory "suddenly appears" and surprises sshd
                except subprocess.CalledProcessError as e:
                  print(f'Command {e.cmd} failed with error {e.returncode}')
              except Exception as e:
                if isinstance(e, KeyboardInterrupt):
                  raise e
                print(datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y"))
                traceback.print_tb(e.__traceback__)
                print(str(e), file = sys.stderr)
          
          # Delete all users present on system but not in authorized_keys file
          for user in su_set:
            if not user in ku_set:
              # Delete user
              try:
                try:
                  print(f"Deleting system user {user} not present in authorized_keys...")
                  subprocess.run(['deluser', '--remove-home', user], check=True)
                except subprocess.CalledProcessError as e:
                  print(f'Command {e.cmd} failed with error {e.returncode}')
              except Exception as e:
                if isinstance(e, KeyboardInterrupt):
                  raise e
                print(datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y"))
                traceback.print_tb(e.__traceback__)
                print(str(e), file = sys.stderr)


          time.sleep(5)
    except (KeyboardInterrupt, Exception) as e:
      if isinstance(e, KeyboardInterrupt):
        raise e
      traceback.print_tb(e.__traceback__)
      print(repr(e))




if __name__ == "__main__":
  #old_stdout = sys.stdout
  #old_stderr = sys.stderr
  #with open("logs/keyimportd_out.log", 'a') as out:
  #  with open("logs/keyimportd_err.log", 'a') as err:
  #    sys.stdout = out
  #    sys.stderr = err
  main(sys.argv)
  #sys.stdout = old_stdout
  #sys.stderr = old_stderr