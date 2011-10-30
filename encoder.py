#!/usr/bin/python

import Pyro4
import os
import platform
import re
import logging
from threading import Timer
import subprocess
from encoder_cfg import pyro_host, pyro_port, ftp_host, ftp_port, ftp_user, ftp_pass
from encoder_cfg import IDLE, RUNNING, Task, getLanIP
from ftplib import FTP
import socket
    
handbrake_unix = '/usr/bin/HandBrakeCLI'
handbrake_win32 = 'C:\\Program Files\\Handbrake\\HandBrakeCLI.exe'
handbrake_win64 = 'C:\\Program Files (x86)\\Handbrake\\HandBrakeCLI.exe'

class Encoder(object):
    def __init__(self):
        self.homedir = os.path.expanduser("~")
        self.central = Pyro4.Proxy('PYRONAME:central.encoding@{0}:{1}'.format(pyro_host,pyro_port))
        self.handbrake = ''
        if os.path.exists(handbrake_unix):
            self.handbrake = handbrake_unix
        elif os.path.exists(handbrake_win32):
            self.handbrake = handbrake_win32
        elif os.path.exists(handbrake_win64):
            self.handbrake = handbrake_win64
        self.status = IDLE
        self.name = 'encoder.{0}'.format(platform.node())
        self.encodeProc = None
        self.timer = Timer(10,self.checkForTask)
        self.timer.start()
    
    def getName(self):
        return self.name
    
    def getLine(self):
        line = ''
        while True:
            out = self.encodeProc.stdout.read(1)
            if out:
                if out == '\r':
                    break
            if not out:
                break
            line += out
        return line
    
    def checkForTask(self):
        if self.status == RUNNING:
            if self.encodeProc:
                if self.encodeProc.poll() is not None:
                    if os.path.exists(os.path.join(self.homedir,self.task.getOutputName())):
                        if not self.sendVideo():
                            self.task.setErrors('Unable to send video')
                    os.unlink(os.path.join(self.homedir,self.task.getOutputName()))
                    self.task.taskFinished()
                    self.task.setCompleted(100)
                    self.central.finishTask(self.task)
                    self.cleanUp()
                    return
                else:
                    if not self.central.updateTask(self.task):
                        self.cancel(self.task.getName())
            else:
                self.status = IDLE
        else:
            failed = False
            self.task = self.central.getTask(self.getName())
            if self.task:
                self.status = RUNNING
                if self.getVideo(self.task.getName()):
                    self.encodeVid()
                else:
                    failed = True
            if failed:
                self.central.finishTask(self.task)
                self.status = IDLE
        self.timer = Timer(2,self.checkForTask)
        self.timer.start()
        
    def cleanUp(self):
        if os.path.exists(os.path.join(self.homedir,self.task.getOutputName())):
                os.unlink(os.path.join(self.homedir,self.task.getOutputName()))
        self.updateTimer.cancel()
        self.timer.cancel()
        self.task = None
        self.status = IDLE
        self.timer = Timer(2,self.checkForTask)
        self.timer.start()
        
    def cancel(self,name):
        if self.task:
            if self.task.getName() == name:
                if self.encodeProc:
                    self.encodeProc.kill()
                    self.cleanUp()
                    return True
        return False
        
    def updateCompleted(self):
        out = self.getLine()
        if out:
            match = re.search('(\d+\.\d+)\s\%',out)
            if match:
                completed = match.group(1)
                self.task.setCompleted(completed)
        if self.encodeProc:
            if self.encodeProc.poll() is None:
                self.updateTimer = Timer(.1,self.updateCompleted)
                self.updateTimer.start()

    def getStatus(self):
        return self.status
    
    def sendVideo(self):
        ftp = FTP()
        ftp.connect(ftp_host,ftp_port)
        ftp.login(ftp_user, ftp_pass)
        ftp.storbinary('STOR {0}'.format(self.task.getOutputName()),open(os.path.join(self.homedir,self.task.getOutputName()),'rb'))
        return True
            
    def getVideo(self,video):
        ftp = FTP()
        ftp.connect(ftp_host,ftp_port)
        ftp.login(ftp_user, ftp_pass)
        ftp.retrbinary('RETR {0}'.format(video), open(os.path.join(self.homedir,video),'wb').write)
        return True
        
    def encodeVid(self):
        self.task.setOutputName(re.sub('\.\w*$','.{0}'.format(self.task.getFormat()),self.task.getName()))
        self.task.taskStarted()
        args = [self.handbrake]
        if self.task.getEncoder():
            args.extend(['-e',self.task.getEncoder()])
        if self.task.getFormat():
            args.extend(['-f',self.task.getFormat()])
        if self.task.getQuality():
            args.extend(['-q',self.task.getQuality()])
        if self.task.getLarge():
            args.append('-4')
        args.extend(['-i',os.path.join(self.homedir,self.task.getName()),'-o',os.path.join(self.homedir,self.task.getOutputName())])
        self.encodeProc = subprocess.Popen(args,stdout=subprocess.PIPE)
        self.updateTimer = Timer(.1,self.updateCompleted)
        self.updateTimer.start()

def main():
    encoder = Encoder()
    daemon = Pyro4.Daemon(host=getLanIP())
    uri = daemon.register(encoder)
    ns = Pyro4.locateNS(host=pyro_host,port=pyro_port)
    try:
        ns.remove(encoder.getName())
    except:
        pass
    ns.register(encoder.getName(),uri)
    daemon.requestLoop()
    
if __name__ == "__main__":
    main()