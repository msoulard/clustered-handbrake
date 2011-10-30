#!/usr/bin/python

import datetime
import socket
import re

# Used for finding your (nonlocalhost) lan ip
lan_regex = '192\.168\.5\..*'

# The ip:port that pyro naming runs on
pyro_host = '192.168.5.195'
pyro_port = 9005

# FTP server connection info
ftp_host = '192.168.5.195'
ftp_port = 9004
ftp_user = 'dist'
ftp_pass = 'encoder'

# Valid engine states
IDLE = 'idle'
RUNNING = 'running'

#max number of times to find pyro naming
max_tries = 5

def getLanIP():
    """
        Used to attempt to grab the system's non 127.0.0.1 IP using the lan_regex property
    """
    for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
        if re.search(lan_regex,ip):
            return ip

class Task(object):
    """
        The common task object which all the components use
    """
    def __init__(self,name,encoder,format,large,quality):
        self.name = name
        self.encoder = encoder
        self.format = format
        self.large = large
        self.quality = quality
        self.started = None
        self.finished = None
        self.errors = None
        self.output = None
        self.added = datetime.datetime.now()
        self.completed = 0

    def getAdded(self):
        return self.added

    def getFormat(self):
        return self.format

    def getEncoder(self):
        return self.encoder

    def getLarge(self):
        return self.large

    def getQuality(self):
        return self.quality
        
    def reset(self):
        self.started = None
        self.finished = None
        self.errors = None
        self.output = None
        self.completed = 0
        
    def setCompleted(self,completed):
        self.completed = completed
        
    def getCompleted(self):
        return self.completed
        
    def setOutputName(self,name):
        self.output = name
        
    def getOutputName(self):
        return self.output
        
    def getName(self):
        return self.name
    
    def taskStarted(self):
        self.started = datetime.datetime.now()
        
    def taskFinished(self):
        self.finished = datetime.datetime.now()
            
    def getStarted(self):
        return self.started
    
    def getFinished(self):
        return self.finished
        
    def setErrors(self,errors):
        self.errors = errors
        
    def getErrors(self):
        return self.errors
    
    def duration(self):
        if self.started and self.finished:
            return self.started - self.finished
        return None