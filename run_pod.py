#!/usr/bin/env python3
from kubernetes import config, client, utils, watch
import os
import sys
import random
import yaml
import string
import time
import threading
import psutil
import traceback
import base64
import argparse
import shlex
import json
import subprocess
import datetime

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

# https://stackoverflow.com/a/56398787
def getRandomLabel(size):
  alphabet = string.ascii_lowercase + string.digits
  return ''.join(random.choices(alphabet, k=size))

def watch_pod(v1, namespace, pod_name):
  w = watch.Watch()
  return (w, w.stream(v1.list_namespaced_pod, namespace=namespace, field_selector=f'metadata.name={pod_name}') )

# Deletes the pod if it exists in the namespace
def delete_pod(v1, namespace, pod_name):
  pod_list = v1.list_namespaced_pod(namespace)
  for pod in pod_list.items:
    if pod.metadata.name == pod_name:
      print("### Deleting pod " + pod_name, file = sys.stdout)
      resp = v1.delete_namespaced_pod(name = pod_name, namespace=namespace)
      # TODO: Check success of deletion?

# Waits for a pod to enter the "Running" phase, and returns True and the last response,
# or returns False and the last response if the timeout has been exceeded.
      
### TODO: Fix a bug where after timeout_seconds, it will still be blocked until the next kubernetes event
def wait_for_pod(v1, watcher, stream, timeout_seconds = 300):

  def stop_watching():
    watcher.stop()

  timer = threading.Timer(timeout_seconds, stop_watching)
  timer.start()

  lastEvent = None
  for event in stream:
    lastEvent = event['object']
    if lastEvent.status.phase == "Running":
      timer.cancel()  # Cancel the timer if the desired state is reached
      return (True, lastEvent)
  return (False, lastEvent)

# Creates a Pod container object, retrieving and changing attributes as needed
def define_pod(v1, pod_manifest_dict, new_name, username, encrypted_password, public_key, volume_id, timeoutsecs, podtype, volume_claim_name = None):
  pod_manifest_dict["metadata"]["name"] = new_name # Update Pod name
  #print(pod_manifest_dict)
  pod_manifest_dict["spec"]["containers"][0]["volumeMounts"][0]["mountPath"] = "/home/" + username # Set home directory name mount
  pod_manifest_dict["spec"]["containers"][0]["volumeMounts"][0]["subPath"] = volume_id # Set subdirectory for persistent volume
  #pod_manifest_dict["spec"]["containers"][0]["volumeMounts"][0]["name"] = new_name
  pod_manifest_dict["spec"]["containers"][0]["args"] = [username, encrypted_password, public_key]

  # Apply labels
  if not pod_manifest_dict["metadata"]["labels"]:
    pod_manifest_dict["metadata"]["labels"] = {}
  pod_manifest_dict["metadata"]["labels"]["user"] = username
  pod_manifest_dict["metadata"]["labels"]["timeout"] = str(timeoutsecs)
  pod_manifest_dict["metadata"]["labels"]["podtype"] = podtype

  if volume_claim_name is not None:
    pod_manifest_dict["spec"]["containers"][0]["volumeMounts"][0]["name"] = volume_claim_name
    pod_manifest_dict["spec"]["volumes"][0]["name"] = volume_claim_name
    pod_manifest_dict["spec"]["volumes"][0]["persistentVolumeClaim"]["claimName"] = volume_claim_name


  pod_object = client.V1Pod(**pod_manifest_dict)

  return pod_object

# Returns True if there are currently any outgoing connections to the specified ip address
def check_outgoing_connections(ip_address):
  for conn in psutil.net_connections(kind='inet'):
    if conn.status == 'ESTABLISHED' and conn.raddr and conn.raddr.ip == ip_address:
      return True
  return False


def pod_is_present_and_running(v1, namespace, name):
  pod_list = v1.list_namespaced_pod(namespace)
  for pod in pod_list.items:
    if pod.metadata.name == name:
      if pod.status.phase == "Running":
        return True
      return False
  return False

def print_available_types(pod_choices_dict):
  for name, data in pod_choices_dict.items():
    print(f"===== {data['displayName']} =====")
    print(f" - {data['description']}")
    print(f"* To use, specify -t/--type {name}")
    print()

def print_available_storage(storage_choices_dict):
  for name, data in storage_choices_dict.items():
    print(f"[{name}]\n - {data['description']}")
    print(f"* To use, specify -s/--storage {name}")
    print()


# Parses arguments and returns relevant data, or exits with an error code upon invalid data.
# This is the "interactive" part.
def parse_argdata(v1, argv, config_map, namespace, username):
  parser = argparse.ArgumentParser(description="", prog="podondemand")
  # Why do all my arguments start with a t???
  parser.add_argument('-t', '--type', type = str, default = None, nargs = '?', const = 'True', 
                      help = "Specify the pod type to spawn. If no argument provided, outputs a description of all available pod types and closes the connection")
  parser.add_argument('-s', '--storage', type = str, default = None, nargs = '?', const = 'True', 
                      help = "Specify the storage configuration to attach, or list available options")
  parser.add_argument('-l', '--list', action = 'store_true', help = "Shows details of all your sessions that are currently running")
  parser.add_argument('-w', '--timeout', type = int, default = None, help = "Sets the inactivity timeout for the pod, in seconds (after not recieving any connections for --timeout <n> seconds, the pod will be terminated")
  parser.add_argument('-d', '--delete', type = str, default = None, nargs = '*', help = 'Deletes a running pod by name (listed between "===" in --list)')
  args = parser.parse_args(argv) #Parse arguments
  

  if args.delete:
    for delete_arg in args.delete:
      pod_list = v1.list_namespaced_pod(namespace)
      nameset = set(pod.metadata.name for pod in v1.list_namespaced_pod(namespace=namespace, label_selector=f'user={username}').items)
      if not delete_arg in nameset:
        print(f'### Error: no pod named "f{delete_arg}"')
        sys.exit(1)
      print("### Deleting pod " + delete_arg, file = sys.stdout)
      resp = v1.delete_namespaced_pod(name = delete_arg, namespace=namespace)
      sys.exit(0)
  
  storage_name = None
  warn_type = False
  storageChoices = None
  if config_map.data['storageChoices']:
    storageChoices = yaml.safe_load(config_map.data['storageChoices'])
    if args.storage == 'True':
      print_available_storage(storageChoices)
      exit(0)
    if args.storage:
      if not args.storage in storageChoices.keys():
        print(f"Error: no storage type named \"{args.volume}\". Here is a list of available options:")
        print_available_storage(storageChoices)
        exit(int(args.storage != 'True'))
      else:
        storage_name = args.storage
  else:
    if args.storage:
      print("Error: no storage options are defined.")

  choices = yaml.safe_load(config_map.data['podChoices'])
  if args.type == 'True':
    print_available_types(choices)
    sys.exit(0)

  manifests = yaml.safe_load(config_map.data['podManifests'])
  pod_manifest_str = None
  pod_type = None
  if not args.type:
    ch = next( (k for k in choices.keys()) ) # Default to first choice
    warn_type = True
    pod_type = ch
    pod_manifest_str = manifests[ch] # Will throw an exception if there are not matching labels in the yaml definitions
  elif not args.type in choices.keys():
    print(f"Error: no pod type named \"{args.type}\". Here is a list of available types:")
    print_available_types(choices)
    sys.exit(1)
  else: # Normal - the user specified a valid type
    pod_type = args.type
    pod_manifest_str = manifests[pod_type]

  ### Handle timeout
  timeout = None
  if args.timeout:
    timeout = args.timeout
  else:
    timeout = config_map.data["inactivityTimeoutSecs"]

  if args.list:
    print("Your pods:")
    for pod in v1.list_namespaced_pod(namespace=namespace, label_selector=f'user={username}').items:
      print(f"=== {pod.metadata.name} ===")
      deletion_timestamp = pod.metadata.deletion_timestamp
      #deletion_grace_period_seconds = pod.metadata.deletion_grace_period_seconds
      status = None
      if deletion_timestamp: #datetime.datetime.now() - deletion_timestamp <= int(deletion_grace_period_seconds):
        secs = int((datetime.datetime.now().replace(tzinfo=None) - deletion_timestamp.replace(tzinfo=None)).total_seconds())
        grace = pod.metadata.deletion_grace_period_seconds
        status = f"Terminating ({str(secs+grace)} / {str(grace)} seconds)"
      else:
        status = pod.status.phase
      print(f"  status: {status}")
      print(f"  user: {pod.metadata.labels['user']}")
      print(f"  type: {pod.metadata.labels['podtype']}")
      print(f"  timeout: {pod.metadata.labels['timeout']} seconds")
      print(f"  node: {pod.spec.node_name}")
      timestr = None
      if pod.status:
        timestr = datetime.datetime.now().replace(tzinfo=None) - pod.status.start_time.replace(tzinfo=None)
      print(f"  run time: {timestr}")
      print_ssh_connect_str(v1, config_map, pod, namespace, username)
      print()
    sys.exit(0)
  
  return (args, pod_type, pod_manifest_str, timeout, storage_name, warn_type)

def print_ssh_connect_str(v1, config_map, pod, namespace, username):
  # Obtain specified service for this pod to obtain the connection address
  service = v1.read_namespaced_service(name = config_map.data["serviceName"], namespace = namespace)
  pod_ip = pod.status.pod_ip ###resp.status.pod_ip
  #print(service.status)
  # TODO: fully parameterize this?
  pod_host_ip = pod.status.pod_ip ###resp.status.host_ip
  if pod_host_ip == None or pod_host_ip == "":
    pod_host_ip = random.choice(service.status.load_balancer.ingress).ip
  #print(f'ssh -J "jumper@math.knox.edu,{os.getenv("USER")}@{pod_host_ip}:30142" "{username}@{pod_ip}" -i ~/.ssh/YOUR_JUMPER_KEY.rsa') # TODO Further parametrize this?
  # "knox_jump,{os.getenv("USER")}@{pod_host_ip}:30142"
  #print("Note: considering adding -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null to disable host key checking against pod\n", file = sys.stderr)
  print(" --- Connect using SSH, or use SFTP to browse and transfer files --- ")
  print(f'ssh -J "{os.getenv("USER")}@podondemand" "{username}@{pod_ip}" -i ~/.ssh/yourpodkey_rsa') # TODO Further parametrize this?
  print(f'sftp -i ~/.ssh/yourpodkey_rsa -J "{os.getenv("USER")}@podondemand" "{username}@{pod_ip}"')
  #print(f'\n --- To browse and transfer files ---:\n  sftp -i ~/.ssh/yourpodkey_rsa -J "{os.getenv("USER")}@podondemand" "{username}@{pod_ip}"')

def main(argv):
  config.load_incluster_config()
  v1 = client.CoreV1Api()

  # Read config
  namespace = os.environ.get("CONFIG_NAMESPACE", default = "kube-system")
  config_map = v1.read_namespaced_config_map("podondemand-config", namespace)
  #pod_manifest = config_map.data["pod-manifest"]
  #pod_manifest_dict = yaml.safe_load(pod_manifest)

  argdata = os.getenv('SSH_ORIGINAL_COMMAND')
  if argdata == None:
    argdata = ''
  
  
  # Authenticate user, and add info
  username = os.getenv('USER')
  password = "knox"

  # Encode password
  password = "knox"
  passgen = subprocess.run(['openssl', 'passwd', '-1', '-stdin'], input = password.encode('UTF-8'), check = True, capture_output = True)       
  encrypted_password = passgen.stdout.decode('ascii')
  encrypted_password = encrypted_password.replace('\n', '')

  #args = pod_type = pod_manifest_dict = None
  args, pod_type, pod_manifest_dict, timeout, storage_name, warn_type = parse_argdata(v1, shlex.split(argdata), config_map, namespace, username)

  
  # Will raise an exception if not present
  with open(os.path.expanduser(f'/home/{username}/.ssh/authorized_keys'), 'rb') as authorized_keys:
    public_key = base64.b64encode(authorized_keys.read()).decode('ascii')


  # Change the name of the pod, and make a Pod API object
    # {pod_manifest_dict['metadata']['name']}
  newName = f"userpod-{username}-{pod_type}-{getRandomLabel(16)}"

  newPod = define_pod(v1, pod_manifest_dict = pod_manifest_dict, new_name = newName, username = username, encrypted_password = encrypted_password, public_key = public_key, volume_id = username, timeoutsecs = timeout, podtype = pod_type, volume_claim_name = storage_name)
  #resp2 = v1.create_namespaced_pod(body=newPod, namespace=namespace) # Actually create a new pod
  
  #pv_manifest_dict = yaml.safe_load(config_map.data["pv-manifest"])
  #pv_manifest_dict["spec"]["storageClassName"] = newName
  #pv_manifest_dict["metadata"]["name"] = newName
  #pv_object = client.V1PersistentVolume(**pv_manifest_dict)

  #pvc_manifest_dict = yaml.safe_load(config_map.data["pvc-manifest"])
  #pvc_manifest_dict["spec"]["storageClassName"] = newName
  #pvc_manifest_dict["metadata"]["name"] = newName
  #pvc_object = client.V1PersistentVolumeClaim(**pvc_manifest_dict)
  
  try:
    #print("### Creating PersistentVolume...", file = sys.stderr)
    #resp = v1.create_persistent_volume(body = pv_manifest_dict)
    #print("### Creating PersistentVolumeClaim...", file = sys.stderr)
    #resp = v1.create_namespaced_persistent_volume_claim(body = pvc_manifest_dict, namespace = namespace)
    if warn_type:
      print(f"### Warning: No pod --type specified. Defaulting to first defined, \"{pod_type}\". Specify a custom type by passing the \"--type <name>\" argument into SSH, or retrieve a description of all types using \"--type\" alone. For more information, try --help. Note: you may need to shell-escape the dashes, unless you add the literal prefix \"--\" after your ssh command.\n", file = sys.stderr)

    print("### Starting pod...", file = sys.stderr)
    watcher, stream = watch_pod(v1, namespace = namespace, pod_name = newName) # Start watching for events
    resp = v1.create_namespaced_pod(body=newPod, namespace=namespace) # Actually create a new pod

    print("### Waiting for pod to come online...", file=sys.stderr)
    status, resp = wait_for_pod(v1, watcher, stream)
    if not status:
      print("### Timeout starting pod. Pod is in state: " + str(resp.status.phase), file=sys.stderr)
      resp = v1.delete_namespaced_pod(name = newName, namespace=namespace)
      exit(1)

    print(f"\n### Pod created! Use the following commands to connect to it via SSH or SFTP:\n(network inactivity timeout: {timeout} seconds)\n", file = sys.stderr)
    print_ssh_connect_str(v1, config_map, resp, namespace, username)
    print()

    
  except (KeyboardInterrupt, Exception) as e:
    #traceback.print_tb(e.__traceback__)
    #print(repr(e))
    if isinstance(e, KeyboardInterrupt):
      print("### Spawn pod cancelled by user!")
    else:
      raise e
    delete_pod(v1, namespace, newName)

if __name__ == "__main__":
  main(sys.argv)