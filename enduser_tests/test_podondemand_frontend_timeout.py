#!/usr/bin/env python3

### Reads and uses the PodOnDemand frontend as would a normal user, to test that all available options work correctly.
# Note: this does NOT test cases where:
# • A user specifies the name of another user's pod to delete

import yaml
import argparse
import sys
import subprocess
from covertable import make, sorters, criteria
import re
import time
import io
import shlex



# Accepts arguments as a list (eg ['--type', 'cpu'])
def run_podondemand_cmd(args: list, show = True):
  if show:
    print("  Running PodOnDemand command: " + str(args))
  #output = io.StringIO('/tmp/pod_test')
  proc = subprocess.Popen(['ssh', 'podondemand', '--'] + [str(s) for s in args], stdout = subprocess.PIPE, stderr = subprocess.PIPE, text = True)
  out, err = proc.communicate(timeout = 120)
  if proc.returncode != 0:
    print("Error in run_podondemand_cmd: " + str(args))
    print("  Stdout: " + out) #completed.stdout)
    print("  Stderr: " + err) #completed.stderr)
    raise subprocess.CalledProcessError(returncode = proc.returncode, cmd = "ssh podondemand -- " + str(args))
  #print("  Stdout: " + out)
  #print("  Stderr: " + err)
  return out #completed.stdout

def run_on_remote_pod(connection_cmd: str, argstr: str):
  print("  Running command on remote pod: " + argstr)
  basecmd = shlex.split(connection_cmd + ' -o "StrictHostKeyChecking no"' + " --") # Returns a list of arguments
  completed = subprocess.run(basecmd + [argstr], capture_output = True, timeout = 120, text = True)
  if completed.returncode != 0:
    print("Error in run_podondemand_cmd: " + str(argstr))
    print("  Stdout: " + completed.stdout)
    print("  Stderr: " + completed.stderr)
    raise subprocess.CalledProcessError()
  return completed.stdout


def get_pod_list(show = True):
  # Check if it is running and healthy in the --list
  output = run_podondemand_cmd(['--list'], show = show)
  # Eliminate the "Your pods:" line
  output = '\n'.join(output.split('\n')[1:])

  # Find listed attributes
  list_dict = {}
  pod_entries = re.split(r'^=== ', output, flags = re.MULTILINE)
  for entry in pod_entries:
    if entry == '':
      continue
    pod_name = entry.split(' ')[0]
    list_dict[pod_name] = {}
    for param in re.findall(r'([A-Za-z0-9]+): (.*)', entry):
      list_dict[pod_name][param[0]] = param[1]

    # Find given commands
    ssh_cmd = re.search('(ssh .*$)', entry, flags = re.MULTILINE)
    assert len(ssh_cmd.groups()) > 0
    ssh_cmd = ssh_cmd.group(1)

    sftp_cmd = re.search('(sftp .*$)', entry, flags = re.MULTILINE)
    assert len(sftp_cmd.groups()) > 0
    sftp_cmd = sftp_cmd.group(1)

    list_dict[pod_name]['ssh_cmd'] = ssh_cmd
    list_dict[pod_name]['sftp_cmd'] = sftp_cmd

  return list_dict

# Note that spawn_pod does not have any particular timeout for when it takes too long to spawn,
# although this is not really in the requirements either. A notably long time, however, could indicate a problem
def spawn_pod(type, storage, timeout = None):
  print(f"  Spawning pod with type={type}, storage={storage}, timeout={timeout}...")
  # Spawn the pod
  extra_args = []
  if timeout:
    extra_args += ['--timeout', timeout]
  if type is not None:
    extra_args += ['--type', type]
  if storage is not None:
    extra_args += ['--storage', storage]
  output = run_podondemand_cmd(extra_args)
  assert ' --- CONNECT' in output.upper()

# Deletes the pod, and waits for it to be fully deleted.
def delete_pod(name):
  print(f"  Deleting pod {name}...")
  output = run_podondemand_cmd(['--delete', name])
  assert "### DELETING POD " + name.upper() in output.upper()
  print("  Waiting for pod to be deleted...")
  t1 = time.time()
  timediff = 0
  while name in list(get_pod_list(show = False).keys()) and timediff < 45: # TODO: this currently assumes the default Kubernetes timeout of 30 seconds (with an extra 10 for it actually killing it, and then an extra 5 for some leeway)
    time.sleep(2)
    timediff = time.time() - t1
  assert timediff < 45
  
#def test_pod_ https://github.com/walkframe/covertable/blob/master/python/README.rst
  

# An error could occur eg. if the value was negative
def test_pod_timeout_expect_error(type, storage, timeout):
  print(f"test_pod_timeout_expect_error: type: {type}, storage: {storage}, timeout: {timeout}")
  try:
    spawn_pod(type = type, storage = storage, timeout = timeout)
  except Exception as e:
    return
  assert False

# Tests that the pod's timeout resorts to the default when not specified or specified as 0.
# If the default timeout is not specified on the command line for this script, this test will not be run.
# Just tests for the actual value of the timeout as assigned to the pod, but does not measure it explicitly.
def test_pod_timeout_default(type, storage, default_timeout):
  print(f"test_pod_timeout_default: storage: {storage}, default_timeout: {default_timeout}")
  spawn_pod(type = type, storage = storage)
  res = get_pod_list()
  assert len(res) == 1 # For now...
  podname = list(res.keys())[0]
  podinfo = res[podname]
  assert podinfo['timeout'] == str(default_timeout) + " seconds"
  delete_pod(podname)


# Holds open a network connection to the pod for a specified number of seconds, then checks if the pod exists.
# The pod should exist both if it waited until before and after its timeout
def test_pod_exists_after_network_activity_duration(type, storage, timeout, network_activity_duration = 0):
  print(f"test_pod_exists_after_network_activity_duration: type: {type}, storage: {storage}, timeout: {timeout}, network: {network_activity_duration}")
  #assert network_activity_wait > timeout
  t1 = time.time()
  res = spawn_pod(type = type, storage = storage, timeout = timeout)
  res = get_pod_list()
  podname = list(res.keys())[0]
  podinfo = res[podname]
  assert len(res) == 1
  t2 = time.time()
  if network_activity_duration > 0:
    waitTime = max(0,network_activity_duration - (t2-t1)) # Compensate for startup time
    if waitTime == 0:
      print("Error: test_pod_exists_under_timeout sampled after the timeout interval ended (startup took too long). Please increase the timeout value")
      assert False
    print(f"  Waiting {waitTime} seconds in simulated network activity before checking if pod still exists...")
    run_on_remote_pod(connection_cmd = podinfo['ssh_cmd'], argstr = f"sleep {waitTime}") # Opens a network connection on the pod for n seconds
  #time.sleep(waitTime)
  res = get_pod_list()
  podname = list(res.keys())[0]
  podinfo = res[podname]
  assert len(res) == 1 # For now...
  #print(res)
  assert podinfo['status'] == 'Running'
  delete_pod(podname) # Cleanup



# Tests that a pod is deleted after its timeout. sample_time is the absolute time, in seconds, it should wait after the initial SPAWN
# of the pod to check if it exists
# Failure to delete the pod or put it in a Terminating state can indicate a problem with the garbage collector daemon
# NOTE: Automatically compensates for network_activity_duration
def test_pod_deleted_after_timeout(type, storage, timeout, sample_time, network_activity_duration):
  print(f"test_pod_deleted_after_timeout: type: {type}, storage: {storage}, timeout: {timeout}, sample_time: {sample_time}, network: {network_activity_duration}")
  assert sample_time > timeout
  t1 = time.time()
  spawn_pod(type = type, storage = storage, timeout = timeout)
  res = get_pod_list()
  podname = list(res.keys())[0]
  podinfo = res[podname]
  assert len(get_pod_list()) == 1
  t2 = time.time()
  waitTime = max(0,sample_time - (t2-t1)) # Compensate for startup time
  if waitTime == 0:
    print("  Error: test_pod_deleted_after_timeout: startup took longer than sample_time. Please increase the timeout value")
    assert False
  if network_activity_duration > 0:
    print(f"  Waiting {network_activity_duration} seconds in simulated network activity...")
    run_on_remote_pod(connection_cmd = podinfo['ssh_cmd'], argstr = f"sleep {network_activity_duration}") # Opens a network connection on the pod for n seconds
  print(f"  Waiting {waitTime} seconds before checking if pod is deleted...")
  time.sleep(waitTime)
  res = get_pod_list()
  assert len(res) <= 1 # For now...
  if len(res) == 0: # If there are no pods running anymore, it is good
    return
  podinfo = res[list(res.keys())[0]]

  # If there is one pod that is currently terminating, it is also good.
  assert len(res) == 0 or podinfo['status'].split(' ')[0] == 'Terminating' # We just want to know if deletion was triggered (either deleted or Terminating)

  delete_pod(list(res.keys())[0]) # This will wait until the pod is fully deleted even if it is already being deleted
# a problem with the network connection detector, or a reminicent network connection of sorts

def main(argv):
  parser = argparse.ArgumentParser(description="", prog="test_podondemand_frontend_functionality")
  parser.add_argument('-p', '--pod-choices', type = str,
    help = 'Specify the path to the pod choices yaml. This should contain a root key called "podChoices", containing the yaml as a string.')
  parser.add_argument('-s', '--storage-choices', type = str,
    help = 'Specify the path to the storage choices yaml. This should contain a root key called "storageChoices", containing the yaml as a string.')
  args = parser.parse_args(argv[1:])
  

  # Retrieve possible pod choices
  pod_factors = None
  with open(args.pod_choices, 'r') as config_map:
    choices = yaml.safe_load(config_map.read())
    assert 'podChoices' in choices.keys()
    choices = yaml.safe_load(choices['podChoices'])
    pod_factors = choices

  # Retrieve possible storage choices
  storage_factors = None
  with open(args.storage_choices, 'r') as config_map:
    choices = yaml.safe_load(config_map.read())
    assert 'storageChoices' in choices.keys()
    choices = yaml.safe_load(choices['storageChoices'])
    storage_factors = choices

  default_timeout = 3600 # NOTE: This will be hard-coded here for now...
  
  # NOTE: Ensure your poll frequency is set to a small value, such as 5 seconds
  timeout_factors = [-5, 0, 20]
  network_factors = [0, 10, 30] # Will test both before and after the timeout
  
  tests = make(
     {'type': list(pod_factors.keys()), 'storage': list(storage_factors.keys()), 'network': network_factors, 'timeout': timeout_factors},  # dict factors
     length=2,  # default: 2
     tolerance=3,  # default: 0
     post_filter=lambda row: not(row['timeout'] < 0 and row['network'] > 0)
  )
  
  for test in tests:
    type, storage, network, timeout = (test['type'], test['storage'], test['network'], test['timeout'])
    if timeout < 0:
      test_pod_timeout_expect_error(type = type, storage = storage, timeout = timeout)
      print("test_pod_timeout_expect_error Succeeded!\n")

    if timeout == 0:
      test_pod_timeout_default(type = type, storage = storage, default_timeout = default_timeout)
      print("test_pod_timeout_default Succeeded!\n")

    if timeout > 0:
      # Note: network_activity_duration is automatically com
      test_pod_deleted_after_timeout(type = type, storage = storage, timeout = timeout, sample_time = timeout + 20, network_activity_duration = network)
      print("test_pod_deleted_after_timeout Succeeded!\n")

    if timeout >= 0 and network > 0:
      test_pod_exists_after_network_activity_duration(type = type, storage = storage, timeout = timeout, network_activity_duration = network)
      print("test_pod_exists_after_network_activity_duration Succeeded!\n")
    






if __name__ == "__main__":
  main(sys.argv)