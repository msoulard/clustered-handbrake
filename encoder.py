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
    """
        Main encoder object
    """
    def __init__(self):
        # The dir which the encoder uses to store video filess it grabs from the central server
        # and files which it generates via handbrake
        # TODO -- make this configurable
        self.homedir = os.path.expanduser("~")

        # Look up the central server
        self.central = Pyro4.Proxy('PYRONAME:central.encoding@{0}:{1}'.format(pyro_host,pyro_port))

        # Determine the handbrake path
        # TODO -- This should probably be configurable too
        self.handbrake = ''
        if os.path.exists(handbrake_unix):
            self.handbrake = handbrake_unix
        elif os.path.exists(handbrake_win32):
            self.handbrake = handbrake_win32
        elif os.path.exists(handbrake_win64):
            self.handbrake = handbrake_win64

        self.status = IDLE

        # The name used to register with Pyro Naming
        # TODO -- Might want to use a better naming scheme, lazy linux users may not set hostnames
        # on all their hosts, meaning we could have multiple encoder.localhost's stepping on eachother
        self.name = 'encoder.{0}'.format(platform.node())

        # Reference the external handbrake process
        self.encodeProc = None

        # This timer will check on the encoder's status every ten seconds
        self.timer = Timer(10,self.checkForTask)
        self.timer.start()
    
    def getName(self):
        return self.name
    
    def getLine(self):
        """
            Read from the handbrake process's stdout one char at a time
            until we hit a \r -- this is a needed because if you try
            a readline it'll hang until it hits \n -- which won't happen
            until handbrake exits -- it updates the vid progress in place
            with multiple \r messages
        """
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
            # We (think) we're doing something
            if self.encodeProc:
                # Handbrake process reference exists
                if self.encodeProc.poll() is not None:
                    # Handbrake has exited
                    # TODO -- we should do some validation on the handbrake exit code, just checking that the
                    # output file exists is pretty weak
                    if os.path.exists(os.path.join(self.homedir,self.task.getOutputName())):
                        # Since this file exists we assume things succeeded, FTP the video to the central server
                        if not self.sendVideo():
                            self.task.setErrors('Unable to send video')

                    # Complete the task and inform the central server that we're done
                    self.task.taskFinished()
                    self.task.setCompleted(100)
                    self.central.finishTask(self.task)
                    self.cleanUp()
                    return
                else:
                    # We're not done yet, but handbrake is running, update the central server on our progress
                    if not self.central.updateTask(self.task):
                        self.cancel(self.task.getName())
            else:
                # Don't know why we think we're running -- probably a corner case here, but let's go back to IDLE
                self.status = IDLE
        else:
            failed = False
            # Try to get at ask from the central server
            self.task = self.central.getTask(self.getName())
            if self.task:
                # We got a task, set our status to running, grab the video via FTP from the server and begin the encode
                # process
                self.status = RUNNING
                if self.getVideo(self.task.getName()):
                    self.encodeVid()
                else:
                    failed = True
            if failed:
                # Something bad happened with FTP, fail the task and tell the server
                self.central.finishTask(self.task)
                self.status = IDLE
        # Reschedule the task so we'll check our state again in two seconds
        self.timer = Timer(2,self.checkForTask)
        self.timer.start()
        
    def cleanUp(self):
        """
            Various clean up operations that need to be performed
                - Delete the video files, we shouldn't need them by now
                - Cancel the update timer if it's still active since HB has exited
                - Go back to IDLE
                - Reschedule the main method timer
        """
        if os.path.exists(os.path.join(self.homedir,self.task.getOutputName())):
                os.unlink(os.path.join(self.homedir,self.task.getOutputName()))
        if os.path.exists(os.path.join(self.homedir,self.task.getName())):
                os.unlink(os.path.join(self.homedir,self.task.getName()))
        self.updateTimer.cancel()
        self.timer.cancel()
        self.task = None
        self.status = IDLE
        self.timer = Timer(2,self.checkForTask)
        self.timer.start()
        
    def cancel(self,name):
        """
            External call point to cancel the active task, used by the central server upon user request,
            kills the handbrake process and cleans up
        """
        if self.task:
            if self.task.getName() == name:
                if self.encodeProc:
                    self.encodeProc.kill()
                    self.cleanUp()
                    return True
        return False
        
    def updateCompleted(self):
        """
            Timed method which gets the percentage completed from the handbrake stdout and updates the task
        """
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
        """
            Sends the encoded video back to the central server
        """
        ftp = FTP()
        ftp.connect(ftp_host,ftp_port)
        ftp.login(ftp_user, ftp_pass)
        ftp.storbinary('STOR {0}'.format(self.task.getOutputName()),open(os.path.join(self.homedir,self.task.getOutputName()),'rb'))
        return True
            
    def getVideo(self,video):
        """
            Grabs the passed video from the central server
        """
        ftp = FTP()
        ftp.connect(ftp_host,ftp_port)
        ftp.login(ftp_user, ftp_pass)
        ftp.retrbinary('RETR {0}'.format(video), open(os.path.join(self.homedir,video),'wb').write)
        return True
        
    def encodeVid(self):
        """
            Kick off the handbrake process with the various settings found in the task as arguements
            Also starts the timer which will parse the handbrake output for completion percentages
        """
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
    # Register encoder with Pyro naming
    daemon = Pyro4.Daemon(host=getLanIP())
    uri = daemon.register(encoder)
    ns = Pyro4.locateNS(host=pyro_host,port=pyro_port)
    try:
        # Remove any stale bindings in naming
        # TODO -- do a little more validation, a 'stale' binding may be a host with a duplicate name
        ns.remove(encoder.getName())
    except:
        pass
    ns.register(encoder.getName(),uri)
    daemon.requestLoop()
    
if __name__ == "__main__":
    main()