# Clustered Handbrake #
So what the hell is it? It's a (fairly) user friendly set of scripts to let you farm out encoding tasks via reasonably easy UI across different computers on your LAN to be encoded via the Handbrake CLI.

**Note** This setup has been tested to work with Python 2.7, Pyro 4.10, pyftpdlib, and wxpython 2.8 on Windows 7 and Fedora Core 14 with Handbrake 0.9.5

# About #
Here's what's what.

  * distributedenc.py -- This is your main server, it maintains information about the tasks which have been added and their current state. It allows you to cancel tasks and will contact registered nodes to kill tasks, etc.
  * encoder.py -- This is, as you may have guessed, the script that connects to the central server and accepts encoding tasks. It wraps Handbrake CLI and provides the server with periodic updates about the progress of its tasks.
  * encoderui.py -- This is the front end. It can be run from any system on the LAN. It gets information about the tasks from the server and displays them in a table, allowing you to cancel, add, and view tasks.
  * encoder\_cfg.py -- This file contains some common definitions (like Task) and also contains some properties -- such as the FTP connection information and Pyro information. (Both of which should be using the IP of the system on your LAN which you're running distributedenc.py on.)

# Getting it up and running #
Enough discussion, let's get down to the nitty gritty. Assuming you have all the requirements satisfied (see the first section) it doesn't take much to get everything up and running.

  1. Edit encoder\_cfg.py and update the ftp and pyro host information to match the IP of the system which you're going to run the server on
  1. Also set lan\_regex to the IP scheme of your LAN, i.e. 192.168.1 or 192.168.0 -- this is used to find the LAN ip of the encoder boxes and prevent them from registering with Pyro Naming with a localhost reference.
  1. encoder.py and encoder\_cfg.py to every host you want to perform encoding on
  1. Start distributedenc.py on the host whose IP you entered in encoder\_cfg.py
  1. Start encoder.py on all encoder hosts
  1. Start encoderui.py and begin encoding!