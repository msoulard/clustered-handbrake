#!/usr/bin/python

import Pyro4
import Pyro4.naming
from Pyro4.naming import NamingError
import threading
import Queue
import datetime
import time
import logging
import os
import subprocess
import multiprocessing
from threading import Timer
from pyftpdlib import ftpserver
from ftplib import FTP
from encoder_cfg import pyro_host, pyro_port, ftp_host, ftp_port, ftp_user, ftp_pass
from encoder_cfg import RUNNING, IDLE, Task, max_tries, getLanIP
        
class CentralEncoding(object):
    def __init__(self,maxTasks=None):
        self.homeDir = os.path.join(os.path.expanduser("~"),'master')
        if not os.path.exists(self.homeDir):
            os.makedirs(self.homeDir)
        self.maxTasks = maxTasks
        self.pending = {}
        self.encoding = {}
        self.finished = {}
        self.cancel = {}
        self.error = {}
        self.timer = Timer(60,self._checkTasks)
        self.timer.start()
        
    def getTasks(self):
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
        return Task(name,encoder,format,large,quality)
    
    def cancelTask(self,name):
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
        if name in self.error.keys():
            return self.retry(name,self.error)
        elif name in self.cancel.keys():
            return self.retry(name,self.cancel)
        return False
    
    def uniqueNameCheck(self,name):
        if name in self.pending.keys() + self.encoding.keys():
            return False
        return True
        
    def addTask(self,name,encoder='x264',format='mp4',large=False,quality='20'):
        logging.info('Adding video {0}'.format(name))
        if self.maxTasks:
            if len(self.pending) >= self.maxTasks:
                return False
        if not self.uniqueNameCheck(name):
            return False
        self.clearTask(name)
        task = self.createTask(name,encoder,format,large,quality)
        self.pending[task.getName()] = task
        return True
        
    def getTask(self,name):
        try:
            task = sorted(self.pending.values(),key=lambda x: x.getAdded())[0]
            #task = self.pending.values()[0]
            print 'getTask',name
            self.pending[task.getName()] = None
            del self.pending[task.getName()]
            self.encoding[task.getName()] = (task,name)
            return task
        except IndexError:
            return None
    
    def removeFromDict(self,dictionary,remove):
        newDict = {}
        for key in dictionary:
            if key != remove:
                newDict[key] = dictionary[key]
        return newDict
    
    def _checkTasks(self):
        logging.info('Checking tasks...')
        for task,name in self.encoding.values():
            try:
                encoder = Pyro4.Proxy('PYRONAME:{0}@{1}:{2}'.format(name,pyro_host,pyro_port))
                if encoder.getStatus() != RUNNING:
                    self.pending.put(task)
                    self.encoding = self.remoteFromDict(self.encoding,task.getName())
            except:
                task.reset()
                self.pending[task.getName()]=task
                self.encoding[task.getName()]=None
                del self.encoding[task.getName()]
        self.timer = Timer(60,self._checkTasks)
        self.timer.start()
        
    def updateTask(self,taskIn):
        task,name = self.encoding[taskIn.getName()]
        try:
            self.encoding[taskIn.getName()] = (taskIn,name)
            return True
        except KeyError:
            return False
    
    def finishTask(self,taskIn):
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
    print host,port
    Pyro4.naming.startNSloop(host, port)
    
def startFTPServer():
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
    central = CentralEncoding()
#    central.addTask('test.flv')
#    central.cancelTask('test.flv')
#    central.retryTask('test.flv')flv
    #task = central.getTask('encoder.SOMETHING')
    #task.setOutputName('test.mp4')
    #central.finishTask(task)
    #print central
    #Pyro4.config.HOST='192.168.5.195'
    daemon = Pyro4.Daemon(host=getLanIP())
    uri = daemon.register(central)
    #uri = uri.replace('localhost',getLanIP())
    print type(uri)
    print uri
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
    #central = multiprocessing.Process(target=startCentralEncoder,name='Central')
    nameServer.daemon = True
    ftpServer.daemon = True
    nameServer.start()
    ftpServer.start()
    #time.sleep(10)
    central.start()
    #central.join()
    #startCentralEncoder()
    
    
if __name__ == "__main__":
    main()