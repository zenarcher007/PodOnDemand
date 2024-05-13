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

# Like delete_namespace, but works with non-namespaced elements, such as PersistentVolumes
#def delete_global(list_func, delete_func, name):
#  print("### Deleting element " + name + " using deletion function " + str(delete_func) + "...", file = sys.stderr)
#  list = list_func()
#  notFonud = True
#  for l in list:
#    if l.metadata.name == name:
#      notFound = False
#      delete_func(name = name)
#  if notFound:
#    return True
#  if [pod.metadata.name for pod in list_func().items]:
#    print("### Deletion failed!", file = sys.stderr)
#    return False
#  return True

# Deletes the namespaced element, with the given list and delete function callbacks
    # Deprecated because... it doesn't seem to work correctly???
#def delete_namespaced(list_namespaced, delete_namespaced, name, namespace):
#  pod_list = list_namespaced(namespace)
#  notFound = True
#  for pod in pod_list.items:
#    if pod.metadata.name == name:
#      print("### Deleting element " + name + " using deletion function " + str(delete_namespaced) + "...", file = sys.stderr)
#      resp = delete_namespaced(name = name, namespace=namespace)
#      notFound = False
#      continue
#  if notFound: # The element was not found in the namespace, so it is assumed it has already been deleted
#    return True
#  pod_list = list_namespaced(namespace)
#  if name in [pod.metadata.name for pod in pod_list.items]: # Return true if element is gone
#    print("### Deletion failed!", file = sys.stderr)
#    return False
#  return True

def delete_namespaced_pod(v1, name, namespace):
  pod_list = v1.list_namespaced_pod(namespace)
  notFound = True
  for pod in pod_list.items:
    if pod.metadata.name == name:
      print("### Deleting pod " + name + "...", file = sys.stderr)
      resp = v1.delete_namespaced_pod(name = name, namespace=namespace)
      notFound = False
      continue
  if notFound: # The element was not found in the namespace, so it is assumed it has already been deleted
    return True
  pod_list = v1.list_namespaced_pod(namespace)
  if name in [pod.metadata.name for pod in pod_list.items]: # Return true if element is gone
    print("### Deletion failed!", file = sys.stderr)
    return False
  return True

def main(argv):
  config.load_incluster_config()
  v1 = client.CoreV1Api()

  # Read config
  namespace = os.environ.get("CONFIG_NAMESPACE", default = "kube-system")
  config_map = v1.read_namespaced_config_map("podondemand-config", namespace)
  #pod_manifest = config_map.data["pod-manifest"]
  #pod_manifest_dict = yaml.safe_load(pod_manifest)

  # Obtain pod "intended" names for identification - so it doesn't go wild and kill everything in the namespace
  #pod_base_name = pod_manifest_dict["metadata"]["name"]
  pod_base_name = "userpod" # A hardcoded search string

  print("Starting garbage collector daemon...", file = sys.stderr)


  daemonize(stdout = os.getenv("HOME") + "/logs/garbagecollectd_out.log", stderr = os.getenv("HOME") + "/logs/garbagecollectd_err.log")
  #daemonize(stdout = sys.stdout, stderr = sys.stderr, stdin = sys.stdin)

  while True:
    try:
      # Poll to check for network inactivity for specified timeout
      oldTime = time.time()
      curTime = oldTime

      #timeout = int(config_map.data["inactivityTimeoutSecs"])
      poll_freq = int(config_map.data["inactivityPollFreq"])
      
      timeout_dict = {}
      while True:
        # Create a Set of active connection ip addresses
        active_connections = {conn.raddr.ip for conn in psutil.net_connections(kind='inet') if conn.status == 'ESTABLISHED' and not (conn.raddr == "" or conn.raddr == ())}

        pod_list = v1.list_namespaced_pod(namespace)
        for pod in pod_list.items:
          name = pod.metadata.name
          if not name.startswith(pod_base_name):
            continue
          pod_timeout = int(pod.metadata.labels['timeout'])
          curtime = time.time()
          if pod.status.pod_ip in active_connections or not name in timeout_dict.keys():
            timeout_dict[name] = curtime
          if curtime - timeout_dict[name] > pod_timeout: #and pod.status.phase == "Running":
            timeout_dict.pop(name)
            #pvDeleted = delete_namespaced(v1.list_namespaced_persistent_volume_claim, v1.delete_namespaced_persistent_volume_claim, namespace, name)
            #pvcDeleted = delete_global(v1.list_persistent_volume, v1.delete_persistent_volume, namespace, name)
            #if pvDeleted and pvcDeleted:
            print("Attempting to delete " + name, end = '', file = sys.stderr)
            result = delete_namespaced_pod(v1, name = name, namespace = namespace)
            #result = delete_namespaced(v1.list_namespaced_pod, v1.delete_namespaced_pod, namespace, name)
            print(" -> successful: " + str(result))
        time.sleep(poll_freq)

    except (KeyboardInterrupt, Exception) as e:
      traceback.print_tb(e.__traceback__)
      print(str(e))


if __name__ == "__main__":
  #old_stdout = sys.stdout
  #old_stderr = sys.stderr
  #with open("logs/garbagecollectd_out.log", 'a') as out:
  #  with open("logs/garbagecollectd_err.log", 'a') as err:
  #    sys.stdout = out
  #    sys.stderr = err
  main(sys.argv)
  #sys.stdout = old_stdout
  #sys.stderr = old_stderr
  