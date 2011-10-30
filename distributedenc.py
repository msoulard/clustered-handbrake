#!/usr/bin/python

import Pyro4
import Pyro4.naming
from Pyro4.naming import NamingError
import threading
import time
import logging
import os
import multiprocessing
from threading import Timer
from pyftpdlib import ftpserver
from encoder_cfg import pyro_host, pyro_port, ftp_port, ftp_user, ftp_pass
from encoder_cfg import RUNNING, Task, max_tries, getLanIP
        
class CentralEncoding(object):
    """ The main server obect
            - Keeps tracks of tasks
            - Periodically pings encoders of active tasks
            - Moves tasks back to pending if encoder has died
            - Provides tasks and task information to all callers
    """
    def __init__(self,maxTasks=None):

        # homeDir is the location where the server will store all videos
        # TODO -- make this configurable
        self.homeDir = os.path.join(os.path.expanduser("~"),'master')
        if not os.path.exists(self.homeDir):
            os.makedirs(self.homeDir)

        # Optional task cap -- server will refuse additional
        # tasks once the cap has been reached
        self.maxTasks = maxTasks

        # Task buckets -- pretty self explanatory
        self.pending = {}
        self.encoding = {}
        self.finished = {}
        self.cancel = {}
        self.error = {}

        # Check up on the tasks every minute
        self.timer = Timer(60,self._checkTasks)
        self.timer.start()
        
    def getTasks(self):
        """ Pull in a list of all the tasks from all the task buckets """
        tasks = {}
        for task in self.pending.values():
            tasks[task.getName()] = (task,None,'Pending')
        for task,name in self.encoding.values():
            tasks[task.getName()] = (task,name,'Encoding')
        for task,name in self.finished.values():
            tasks[task.getName()] = (task,name,'Finished')
        for task,name in self.error.values():
            tasks[task.getName()] = (task,name,'Error')
        for task in self.cancel.values():
            tasks[task.getName()] = (task,None,'Cancelled')
        return tasks

    def createTask(self,name,encoder,format,large,quality):
        """ Worthless function for creating a task -- probably had a purpose before, doesn't now """
        return Task(name,encoder,format,large,quality)
    
    def cancelTask(self,name):
        """ Cancel a task, if the task is active, talk to the encoder, if it's pending, just kill it
        """
        if name in self.pending.keys():
            self.cancel[name] = self.pending[name]
            self.pending[name] = None
            del self.pending[name]
            return True
        if name in self.encoding.keys():
            task,nsname = self.encoding[name]
            encoder = Pyro4.Proxy('PYRONAME:{0}@{1}:{2}'.format(nsname,pyro_host,pyro_port))
            if encoder.cancel(name):
                self.cancel[name] = task
                self.encoding[name] = None
                del self.encoding[name]
                return True
        return False

    def clearTask(self,name):
        """ Clear the given inactive task, just delete the reference, 'nuff said
        """
        if name in self.error.keys():
            del self.error[name]
            return True
        elif name in self.cancel.keys():
            del self.cancel[name]
            return True
        elif name in self.finished.keys():
            del self.finished[name]
            return True
        return False

    def retry(self,key,taskDict):
        """ Retry the given error'ed or cancelled tasks, just reset the task and move it to the pending bucket
        """
        if key in taskDict.keys():
            try:
                task,nsname = taskDict[key]
            except TypeError:
                task = taskDict[key]
            task.reset()
            self.pending[key] = task
            taskDict[key] = None
            del taskDict[key]
            return True
        return False

    def retryTask(self,name):
        """ External call point for retrying a task, finds out which, if any, bucket the inactive task is in
        """
        if name in self.error.keys():
            return self.retry(name,self.error)
        elif name in self.cancel.keys():
            return self.retry(name,self.cancel)
        return False
    
    def uniqueNameCheck(self,name):
        """ Since we identify based on video name, we probably don't want multiple active tasks that have the same
        name, so this ensures no keys exist in the active buckets which equal name
        """
        if name in self.pending.keys() + self.encoding.keys():
            return False
        return True
        
    def addTask(self,name,encoder='x264',format='mp4',large=False,quality='20'):
        """ Called externally to add new tasks
        """
        # TODO -- should probably put in some validation to verify the video 'name' already exists in homedir
        logging.info('Adding video {0}'.format(name))
        if self.maxTasks:
            if len(self.pending) >= self.maxTasks:
                return False
        if not self.uniqueNameCheck(name):
            return False
        # Clear any identical task names from the inactive buckets, inactive tasks are second-class citizens
        # so we simply erase them without warning
        self.clearTask(name)
        task = self.createTask(name,encoder,format,large,quality)
        self.pending[task.getName()] = task
        return True
        
    def getTask(self,name):
        """ External call point for getting a new task, used by remote encoders
            Tasks are selected based on the time they were added, FIFO
        """
        try:
            task = sorted(self.pending.values(),key=lambda x: x.getAdded())[0]
            print 'getTask',name
            self.pending[task.getName()] = None
            del self.pending[task.getName()]
            self.encoding[task.getName()] = (task,name)
            return task
        except IndexError:
            return None
    
    def _checkTasks(self):
        logging.info('Checking tasks...')
        for task,name in self.encoding.values():
            try:
                encoder = Pyro4.Proxy('PYRONAME:{0}@{1}:{2}'.format(name,pyro_host,pyro_port))
                # If the encoder is not running but we think the task is active, then odds may be
                # that the encoder has been reset, we should probably reset the task to pending
                if encoder.getStatus() != RUNNING:
                    self.pending.put(task)
                    self.encoding[task.getName()] = None
                    del self.encoding[task.getName()]
            except:
                # If we get an exception it probably means the encoder is down, so we should
                # reset the task to pending
                # TODO -- Pin down the correct exception to catch, general except is ugly / hackish
                task.reset()
                self.pending[task.getName()]=task
                self.encoding[task.getName()]=None
                del self.encoding[task.getName()]

        # Reschedule the timer since they only execute once
        self.timer = Timer(60,self._checkTasks)
        self.timer.start()
        
    def updateTask(self,taskIn):
        """
            External call point to update a given task, used by encoders to provide update views of tasks to the
            server -- i.e. what percent completed the tasks is in HB
        """
        task,name = self.encoding[taskIn.getName()]
        try:
            self.encoding[taskIn.getName()] = (taskIn,name)
            return True
        except KeyError:
            return False
    
    def finishTask(self,taskIn):
        """
            External call point to let the server know that a task has been completed, if the video
            doesn't exist in homedir, then we assume that this finish call was actually an error,
            depending on the situation move the task to the correct inactive bucket

            Deletes the original video for cleanup if we were successful
        """
        task,name = self.encoding[taskIn.getName()]
        task = taskIn
        if os.path.exists(os.path.join(self.homeDir,task.getOutputName())):
            self.finished[task.getName()] = (taskIn,name)
            self.encoding[task.getName()] = None
            del self.encoding[task.getName()]
            os.unlink(os.path.join(self.homeDir,task.getName()))
            return True
        else:
            self.error[task.getName()] = (taskIn,name)
            self.encoding[task.getName()] = None
            del self.encoding[task.getName()]
            return False
        
def startNameServer(host,port):
    """
        Start Pyro naming server for the server and encoders to register and look up with

        This is the backbone of the system -- this NEEDS to run!
    """
    print host,port
    Pyro4.naming.startNSloop(host, port)
    
def startFTPServer():
    """
        Starts an FTP server so that the encoders, ui, and server can swap files back and forth
    """
    homeDir = os.path.join(os.path.expanduser("~"),'master')
    if not os.path.exists(homeDir):
        os.makedirs(self.homeDir)
    print homeDir
    auth = ftpserver.DummyAuthorizer()
    auth.add_user(ftp_user,ftp_pass,homeDir,perm='elrwda')
    
    handler = ftpserver.FTPHandler
    handler.authorizer = auth
    address = ("0.0.0.0",ftp_port)
    ftpd = ftpserver.FTPServer(address,handler)
    ftpd.serve_forever()
    
def startCentralEncoder():
    """
        Start the central server and register it with Pyro
    """
    central = CentralEncoding()
    daemon = Pyro4.Daemon(host=getLanIP())
    uri = daemon.register(central)
    tries = 0
    while(tries < max_tries):
        try:
            ns = Pyro4.locateNS(host=pyro_host,port=pyro_port)
            break
        except NamingError:
            tries += 1
            if tries >= max_tries:
                print 'Giving up, too many tries'
                raise
            print 'Couldn\'t find naming, waiting for 1 seconds'
            time.sleep(1)
    ns.register('central.encoding',uri)
    daemon.requestLoop()
    
def main():
    nameServer = multiprocessing.Process(target=startNameServer,name='Pyro-Naming',args=[pyro_host,pyro_port])
    ftpServer = multiprocessing.Process(target=startFTPServer,name='FTP-Server')
    central = threading.Thread(target=startCentralEncoder,name='Central')
    nameServer.daemon = True
    ftpServer.daemon = True
    nameServer.start()
    ftpServer.start()
    central.start()
    
if __name__ == "__main__":
    main()