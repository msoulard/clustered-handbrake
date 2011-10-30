#!/usr/bin/python

import wx
import wx.grid
import wx.lib.agw.aui as aui
import Pyro4
import os
import threading
from encoder_cfg import pyro_host, pyro_port, ftp_host, ftp_port, ftp_user, ftp_pass
from encoder_cfg import IDLE, RUNNING, Task
from ftplib import FTP
import textwrap

statusMapping = {
        'Encoding':'a',
        'Pending':'b',
        'Finished':'c',
        'Cancelled':'d',
        'Error':'e',
}

class TaskTable(wx.grid.PyGridTableBase):
    def __init__(self, data, rowLabels=None, colLabels=None):
        wx.grid.PyGridTableBase.__init__(self)
        self.data = data
        self.rowMapping = {}
        self.rowLabels = rowLabels
        self.colLabels = colLabels

    def sortData(self,data):
        data =  sorted(data, key=lambda x: statusMapping[x[1]]+str(x[6]))
        return data
        
    def updateData(self,data,grid):
        start = len(self.data)
        end = len(data)
        newRows = []
        updatedNames = []
        selectedNames = []
        for row in grid.GetSelectedRows():
            selectedNames.append(self.data[row][0])
        data = self.sortData(data)
        for row, info in enumerate(data):
            name, status, nsName, completed, started, finished, added = info
            updatedNames.append(name)
            self.rowMapping[name] = row
            if row >= len(self.data):
                self.data.append([name,status,nsName,completed,started,finished,added])
            self.SetValue(row,1,status)
            self.SetValue(row,2,nsName)
            self.SetValue(row,3,completed)
            self.SetValue(row,4,started)
            self.SetValue(row,5,finished)
            self.data[row] = [name,status,nsName,completed,started,finished,added]
        for row in newRows:
            self.data.append(row)
            rowNum = self.data.index(row)
            self.rowMapping[row[0]]=rowNum
            for i in xrange(0,6):
                self.SetValue(row,i,row[i])
        for name in self.rowMapping.keys():
            if name not in updatedNames:
                del self.rowMapping[name]
        grid.ClearSelection()
        for name in selectedNames:
            if name in self.rowMapping:
                grid.SelectRow(self.rowMapping[name],True)
        for row in xrange(end,start):
            del self.data[row]
        if end < start:
            msg = wx.grid.GridTableMessage(self,wx.grid.GRIDTABLE_NOTIFY_ROWS_DELETED,end,start-end)
            grid.ProcessTableMessage(msg)
        elif end > start:
            msg = wx.grid.GridTableMessage(self,wx.grid.GRIDTABLE_NOTIFY_ROWS_APPENDED,end-start)
            grid.ProcessTableMessage(msg)
            
    def GetNumberRows(self):
        return len(self.data)
    
    def GetNumberCols(self):
        return len(self.colLabels)
        #try:
        #    return len(self.data[0])
        #except IndexError:
        #    return 0
        
    def GetColLabelValue(self,col):
        if self.colLabels:
            return self.colLabels[col]
    
    def GetRowLabelValue(self,row):
        if self.rowLabels:
            return self.rowLabels[row]
        return ''
        
    def IsEmptyCell(self,row,col):
        #return bool(self.data[row][col])
        return False
    
    def getRows(self,rows):
        ret = []
        for row in rows:
            ret.append(self.data[row])
        return ret
    
    def GetValue(self,row,col):
        if not self.data:
            return ''
        if col == 0:
            self.rowMapping[self.data[row][col]]=row
        return self.data[row][col]
    
    def SetValue(self,row,col,value):
        pass
    
    #def GetTypeName(self,row,col):
     #   return type(self.data[row][col])

    
class TaskGrid(wx.grid.Grid):
    def __init__(self,parent,data,rowLabels=None,colLabels=None):
        wx.grid.Grid.__init__(self,parent,-1)
        self.rowLabels = rowLabels
        self.colLabels = colLabels
        #self.SetData(data)
        self.SetTable(TaskTable([],self.rowLabels,self.colLabels))
        self.SetData(data)
        #self.AutoSizeColumns(setAsMin=True)
        #self.AutoSizeRows()
        self.SetColSize(0,300)
        self.SetColSize(1,50)
        self.SetColSize(2,150)
        self.SetColSize(3,70)
        self.SetColSize(4,150)
        self.SetColSize(5,150)
        self.SetRowLabelSize(0)
        self.EnableEditing(False)
        self.SetSelectionMode(1)
        
    def getRows(self,rows):
        return self.GetTable().getRows(rows)
        
    def SetData(self,data):
        self.GetTable().updateData(data,self)
        #self.SetTable(TaskTable(data,self.rowLabels,self.colLabels))
        #self.AutoSizeColumns(setAsMin=True)
        #self.AutoSizeRows()
        #self.EnableEditing(False)
        self.ForceRefresh()

class taskViewDialog(wx.Dialog):
    def __init__(self,parent,rows,table):
        self._parent = parent
        self._table = table
        self.rows = rows
        if not rows or not table:
            self.Close()
        rows = table.getRows(rows)
        tasks = []
        tasksIn = self._parent.central.getTasks()
        for row in rows:
            if row[0] in tasksIn:
                tasks.append(row[0])
        if not tasks:
            self.Close()
        label = 'Detailed Task View'
        wx.Dialog.__init__(self,parent,-1,label,wx.DefaultPosition,wx.Size(310,400))

        mainBox = wx.BoxSizer(wx.VERTICAL)
        self.taskChooser = wx.ListBox(self,-1,style=wx.LB_HSCROLL|wx.LB_SINGLE,size=wx.Size(250,100))
        #self.taskChooser = wx.ComboBox(self,-1,tasks[0],choices=tasks,size=wx.Size(400,100),style=wx.CB_READONLY|wx.CB_SORT|wx.CB_DROPDOWN)
        taskPanel = wx.Panel(self,-1)
        taskSizer = wx.FlexGridSizer(rows=12,cols=2,hgap=10,vgap=5)
        taskNameLabel = wx.StaticText(taskPanel,label='Name:')
        self.taskName = wx.StaticText(taskPanel,label='')
        taskOutNameLabel = wx.StaticText(taskPanel,label='Output Name:')
        self.taskOutName = wx.StaticText(taskPanel,label='')
        taskAddedLabel = wx.StaticText(taskPanel,label='Added:')
        self.taskAdded = wx.StaticText(taskPanel,label='')
        taskStatusLabel = wx.StaticText(taskPanel,label='Status:')
        self.taskStatus = wx.StaticText(taskPanel,label='')
        taskEncoderLabel = wx.StaticText(taskPanel,label='Assigned Encoder:')
        self.taskEncoder = wx.StaticText(taskPanel,label='')
        taskCompletedLabel = wx.StaticText(taskPanel,label='Completed:')
        self.taskCompleted = wx.StaticText(taskPanel,label='')
        taskStartedLabel = wx.StaticText(taskPanel,label='Started:')
        self.taskStarted = wx.StaticText(taskPanel,label='')
        taskFinishedLabel = wx.StaticText(taskPanel,label='Finished:')
        self.taskFinished = wx.StaticText(taskPanel,label='')
        ### HB Info
        taskEncLabel = wx.StaticText(taskPanel,label='Encoder:')
        self.taskEnc = wx.StaticText(taskPanel,label='')
        taskFormatLabel = wx.StaticText(taskPanel,label='Format:')
        self.taskFormat = wx.StaticText(taskPanel,label='')
        taskLargeLabel = wx.StaticText(taskPanel,label='Large:')
        self.taskLarge = wx.StaticText(taskPanel,label='')
        taskQualityLabel = wx.StaticText(taskPanel,label='Quality:')
        self.taskQuality = wx.StaticText(taskPanel,label='')
        taskSizer.AddMany([taskNameLabel,self.taskName,taskOutNameLabel,self.taskOutName,
                           taskAddedLabel,self.taskAdded,
                           taskStatusLabel,self.taskStatus,taskEncoderLabel,self.taskEncoder,
                           taskCompletedLabel,self.taskCompleted,
                           taskStartedLabel,self.taskStarted,taskFinishedLabel,self.taskFinished,
                           taskEncLabel,self.taskEnc,taskFormatLabel,self.taskFormat,
                           taskLargeLabel,self.taskLarge,taskQualityLabel,self.taskQuality,
                           ])
        taskPanel.SetSizer(taskSizer)

        self.tasksIn = tasksIn

        #self.changed()

        close = wx.Button(self,-1,'Close')

        mainBox.Add(self.taskChooser)
        mainBox.Add(taskPanel)
        mainBox.Add(close)

        self.SetSizer(mainBox)
        for task in tasks:
            self.taskChooser.Insert(task,0)
        self.tasks = tasks
        self.changed()
        self.taskChooser.SetSelection(0)
        self.Bind(wx.EVT_BUTTON,self.close,close)
        self.Bind(wx.EVT_LISTBOX,self.changed,self.taskChooser)

    def changed(self,evt=None):
        id = self.tasks[self.taskChooser.GetSelection()]
        task,encoder,status = self.tasksIn[id]
        self.taskName.SetLabel('\n'.join(textwrap.wrap(id,35)))
        if task.getOutputName():
            self.taskOutName.SetLabel('\n'.join(textwrap.wrap(task.getOutputName(),35)))
        self.taskAdded.SetLabel(str(task.getAdded()))
        #self.taskOutName.SetLabel(task.getOutputName())
        self.taskStatus.SetLabel(status)
        if encoder:
            self.taskEncoder.SetLabel(encoder)
        self.taskCompleted.SetLabel(str(task.getCompleted()))
        if task.getStarted():
            self.taskStarted.SetLabel(str(task.getStarted()))
        if task.getFinished():
            self.taskFinished.SetLabel(str(task.getFinished()))
        self.taskEnc.SetLabel(task.getEncoder())
        self.taskFormat.SetLabel(task.getFormat())
        self.taskLarge.SetLabel(str(task.getLarge()))
        self.taskQuality.SetLabel(task.getQuality())

    def close(self,evt=None):
        self.Close()

class addEncodeDialog(wx.Dialog):
    def __init__(self,parent):
        self._parent = parent
        label = 'Add Encode'
        self.vids = []
        self.dir = None
        wx.Dialog.__init__(self,parent,-1,label,wx.DefaultPosition,wx.Size(325,430))
        buttonPanel = wx.Panel(self,-1,size=(-1,32))
        
        filePanel = wx.Panel(self,-1)
        fileBox = wx.BoxSizer(wx.VERTICAL)
        self.vidBox = wx.ListBox(filePanel,-1,style=wx.LB_EXTENDED|wx.LB_HSCROLL,size=wx.Size(300,200))
        fileButtonPanel = wx.Panel(filePanel,-1)
        fileButtonBox = wx.BoxSizer(wx.HORIZONTAL)
        addVids = wx.Button(fileButtonPanel,-1,'Browse')
        clearVids = wx.Button(fileButtonPanel,-1,'Clear')
        fileButtonBox.Add(addVids)
        fileButtonBox.Add(clearVids)
        fileButtonPanel.SetSizer(fileButtonBox)
        fileBox.Add(self.vidBox)
        fileBox.Add(fileButtonPanel)
        filePanel.SetSizer(fileBox)
        add = wx.Button(buttonPanel,-1,'Add')
        cancel = wx.Button(buttonPanel,-1,'Cancel')

        mainBox = wx.BoxSizer(wx.VERTICAL)

        encodePanel = wx.Panel(self,-1)
        formSizer = wx.FlexGridSizer(rows=4,cols=2,hgap=10,vgap=5)
        encoderLabel = wx.StaticText(encodePanel,label='Encoder')
        self.encoder = wx.ComboBox(encodePanel,-1,value='x264',choices=['x264','ffmpeg','theora'],style=wx.CB_READONLY|wx.CB_SORT|wx.CB_DROPDOWN)
        formatLabel = wx.StaticText(encodePanel,label='Format')
        self.format = wx.ComboBox(encodePanel,-1,value='mp4',choices=['mp4','mkv'])
        largeLabel = wx.StaticText(encodePanel,label='Large file')
        self.large = wx.CheckBox(encodePanel,-1,'Large Files')
        qualityLabel = wx.StaticText(encodePanel,label='Quality')
        choices = [str(x) for x in xrange(0,52)]
        self.quality = wx.ComboBox(encodePanel,-1,value='20',choices=choices,style=wx.CB_READONLY|wx.CB_SORT|wx.CB_DROPDOWN)
        formSizer.AddMany([encoderLabel,self.encoder,formatLabel,
                           self.format,largeLabel,self.large,qualityLabel,self.quality])
        encodePanel.SetSizer(formSizer)
        buttonBox = wx.BoxSizer(wx.HORIZONTAL)
        buttonBox.Add(add,0,wx.BOTTOM|wx.RIGHT|wx.TOP,5)
        buttonBox.Add(cancel,0,wx.BOTTOM|wx.RIGHT|wx.TOP,5)
        buttonPanel.SetSizer(buttonBox)

        fileGroup = wx.StaticBox(self,-1,'Files')
        fileGroupSizer = wx.StaticBoxSizer(fileGroup,wx.VERTICAL)
        fileGroupSizer.Add(filePanel)
        mainBox.Add(fileGroupSizer,flag=wx.EXPAND)

        encodeGroup = wx.StaticBox(self,-1,'Encode Options')
        encodeGroupSizer = wx.StaticBoxSizer(encodeGroup,wx.VERTICAL)
        encodeGroupSizer.Add(encodePanel)
        mainBox.Add(encodeGroupSizer,flag=wx.EXPAND)
        
        mainBox.Add(buttonPanel)
        self.SetSizer(mainBox)
        self.Bind(wx.EVT_BUTTON,self.close,cancel)
        self.Bind(wx.EVT_BUTTON,self.add,add)
        self.Bind(wx.EVT_BUTTON,self.addVid,addVids)
        self.Bind(wx.EVT_BUTTON,self.clearVid,clearVids)
        
    def add(self,event):
        encoder = self.encoder.GetValue()
        format = self.format.GetValue()
        large = self.large.IsChecked()
        quality = self.quality.GetValue()
        files = self.vids
        dir = self.dir
        self.Close()
        if self.vids and self.dir:
            self._parent.addVideos(encoder,format,large,quality,files,dir)

    def addVid(self,event):
        diag = wx.FileDialog(self,'Select video(s) to add',style=wx.FD_OPEN|wx.FD_MULTIPLE,
                             wildcard="Videos files(*.flv)|*.flv|AVI files(*.avi)|*.avi|MKV files(*.mkv)|*.mkv")
        if diag.ShowModal() == wx.ID_OK:
            self.vids = diag.GetFilenames()
            self.dir = diag.GetDirectory()
            self.changeList()

    def close(self,event=None):
        self.Close()
        
    def clearVid(self,event):
        self.vids=[]
        self.dir = None
        self.changeList()
        
    def changeList(self,event=None):
        """ populates the listbox with the skip list of the valid extension list depending on whath as been selected """
        self.vidBox.Clear()
        for item in self.vids:
            self.vidBox.Insert(item,0,None)

class EncoderFrame(wx.Frame):
    def __init__(self,parent,ID,title,position,size):
        wx.Frame.__init__(self,parent,ID,title,position,size)
        self.mgr = aui.AuiManager(self)
        taskPanel = wx.Panel(self,-1,size=(350,300))
        taskBox = wx.BoxSizer(wx.VERTICAL)
        self.central = Pyro4.Proxy('PYRONAME:central.encoding@{0}:{1}'.format(pyro_host,pyro_port))
        self.ids = {
                    'taskList': wx.NewId(),
                    'addFolder': wx.NewId(),
                    'addVideo': wx.NewId(),
                    'taskTimer': wx.NewId(),
                    'add': wx.NewId(),
                    'cancel': wx.NewId(),
                    'view': wx.NewId(),
                    'clear':wx.NewId(),
                    'retry': wx.NewId(),
                    }
        self.working = False
        self.workingDiag = None
        self.currThread = None
        self.workingTotal = 0
        self.needCancel = False
        self.pendingSends = []
        #self.taskList = easyListCtrl(taskPanel, self.ids['taskList'], mode=easyListCtrl.TASKS, single=False, borders=False)
        self.taskList = TaskGrid(taskPanel,self.getData(),rowLabels=None,colLabels=['Task Name','Status','Assigned Encoder','Completed','Started','Finished'])
        #self.taskList.AutoSize()
        #self.refreshList()
        taskBox.Add(self.taskList,1,wx.EXPAND|wx.ALL)
        hudtoolbar = aui.AuiToolBar(self,-1,wx.DefaultPosition,size=(1000,-1),agwStyle=aui.AUI_TB_DEFAULT_STYLE | aui.AUI_TB_NO_AUTORESIZE | aui.AUI_TB_OVERFLOW | aui.AUI_TB_TEXT | aui.AUI_TBTOOL_TEXT_BOTTOM)
        hudtoolbar.SetToolBitmapSize(wx.Size(40,40))
        hudtoolbar.AddSimpleTool(self.ids['add'],'Add Encode',wx.ArtProvider.GetBitmap(wx.ART_ADD_BOOKMARK))
        hudtoolbar.AddSimpleTool(self.ids['view'],'View',wx.ArtProvider.GetBitmap(wx.ART_FIND))
        hudtoolbar.AddSimpleTool(self.ids['clear'],'Clear',wx.ArtProvider.GetBitmap(wx.ART_DEL_BOOKMARK))
        hudtoolbar.AddSimpleTool(self.ids['retry'],'Retry',wx.ArtProvider.GetBitmap(wx.ART_REDO))
        hudtoolbar.AddSimpleTool(self.ids['cancel'],'Cancel',wx.ArtProvider.GetBitmap(wx.ART_DELETE))
        hudtoolbar.Realize()
        taskPanel.SetSizer(taskBox)
        self.mgr.AddPane(hudtoolbar, aui.AuiPaneInfo().ToolbarPane().Top().Row(1).Gripper(False))
        self.mgr.AddPane(taskPanel, aui.AuiPaneInfo().Center().Floatable(False).MaximizeButton(False).CaptionVisible(False).CloseButton(False))
        self.mgr.SetDockSizeConstraint(.5,.5)
        self.mgr.Update()
        self.Centre()
        self.timer = wx.Timer(self,self.ids['taskTimer'])
        self.timer.Start(4000)
        wx.EVT_TIMER(self,self.ids['taskTimer'],self.refreshList)
        wx.EVT_TOOL(self,self.ids['cancel'],self.cancel)
        wx.EVT_TOOL(self,self.ids['add'],self.add)
        wx.EVT_TOOL(self,self.ids['view'],self.view)
        wx.EVT_TOOL(self,self.ids['clear'],self.clear)
        wx.EVT_TOOL(self,self.ids['retry'],self.retry)
        self.taskList.Bind(wx.grid.EVT_GRID_CELL_LEFT_CLICK,self.handleClick)
        #self.Bind(wx.EVT_IDLE,self.OnIdle)

    def view(self,evt=None):
        taskViewDialog(self,self.taskList.GetSelectedRows(),self.taskList).ShowModal()

    def createSettings(self,encoder,format,large,quality):
        settings = {
                'encoder':encoder,
                'format':format,
                'large':large,
                'quality':quality,
        }
        return settings

    def addVideos(self,encoder,format,large,quality,files,dir):
        self.pendingSends = zip([dir]*len(files),files)
        if not self.pendingSends:
            return
        args = [self.createSettings(encoder,format,large,quality)] + list(self.pendingSends[0])
        self.currThread = threading.Thread(target=self.threadedSend,args=args)
        self.currThread.start()
        self.workingTotal = 0
        self.workingDiag = wx.ProgressDialog('Transfering','Transfering videos to central server',len(files),self,style=wx.PD_ELAPSED_TIME|wx.PD_SMOOTH|wx.PD_AUTO_HIDE)
        self.workingDiag.ShowModal()
        
    def getClosestRow(self,row):
        min = None
        minVal = None
        for rowSel in self.taskList.GetSelectedRows():
            win=False
            diff = abs(row-rowSel)
            if not minVal:
                win=True
            else:
                if diff < minVal:
                    win=True
            if win:
                minVal = diff
                min = rowSel
        return min
        
    def handleClick(self,event):
        row = event.GetRow()
        if event.ControlDown():
            if row in self.taskList.GetSelectedRows():
                self.taskList.DeselectRow(row)
            else:
                self.taskList.SelectRow(row,True)
        elif event.ShiftDown():
            if self.taskList.GetSelectedRows():
                closest = self.getClosestRow(row)
                for x in xrange(min(row,closest),max(row,closest)):
                    self.taskList.SelectRow(x,True)
                self.taskList.SelectRow(row,True)
        else:
            self.taskList.ClearSelection()
            self.taskList.SelectRow(row,True)

    def clear(self,evt):
        for task in self.taskList.getRows((self.taskList.GetSelectedRows())):
            if task[1] in ['Cancelled','Error','Finished']:
                if not self.central.clearTask(task[0]):
                    wx.MessageBox('Could not clear task, was it removed?','Error',style=wx.OK|wx.ICON_WARNING)
                    break
            else:
                wx.MessageBox('Can only clear cancelled, error\'ed, or finished tasks.','Error',style=wx.OK|wx.ICON_WARNING)
                break
        
    def cancel(self,evt):
        for task in self.taskList.getRows(self.taskList.GetSelectedRows()):
            if task[1] in ['Pending','Encoding']:
                if not self.central.cancelTask(task[0]):
                    wx.MessageBox('Could not cancel task, did it finish already?','Error',style=wx.OK|wx.ICON_WARNING)
                    break
            else:
                wx.MessageBox('Can only cancel pending or encoding tasks.','Error',style=wx.OK|wx.ICON_WARNING)
                break

    def retry(self,evt):
        for task in self.taskList.getRows(self.taskList.GetSelectedRows()):
            if task[1] in ['Cancelled','Error']:
                if not self.central.retryTask(task[0]):
                    wx.MessageBox('Could not retry task, did it get removed?','Error',style=wx.OK|wx.ICON_WARNING)
                    break
            else:
                wx.MessageBox('Can only retry cancelled or errored tasks.','Error',style=wx.OK|wx.ICON_WARNING)
                break

    def add(self,evt):
        diag = addEncodeDialog(self)
        diag.ShowModal()
                
    def isActive(self):
        if self.currThread:
            return self.currThread.isAlive()
        return False
    
    def threadDone(self,settings,vid,evt=None):
        self.currThread.join()
        self.currThread = None
        self.central.addTask(vid,**settings)
        del self.pendingSends[0]
        if self.workingDiag.IsShown():
            self.workingTotal += 1
            self.workingDiag.Update(self.workingTotal)
            if not self.pendingSends:
                self.workingDiag.EndModal(wx.ID_OK)
            else:
                args = [settings] + list(self.pendingSends[0])
                self.currThread = threading.Thread(target=self.threadedSend,args=args)
                self.currThread.start()
                
    def threadedSend(self,settings,dir,vid):
        ftp = FTP()
        ftp.connect(ftp_host,ftp_port)
        ftp.login(ftp_user, ftp_pass)
        if not dir.endswith(os.sep):
            dir += os.sep
        ftp.storbinary('STOR {0}'.format(vid),open(os.path.join(dir,vid),'rb'))
        wx.CallAfter(self.threadDone,settings,vid)
    
    def getData(self):
        tasks = self.central.getTasks()
        data = []
        for task,name,status in tasks.values():
            row = [task.getName(),status,name,str(task.getCompleted()),task.getStarted() or ' ',task.getFinished() or ' ',task.getAdded()]
            data.append(row)
        return data

    def refreshList(self,evt=None):
        
        self.taskList.SetData(self.getData())

class FTPThread(threading.Thread):
    def __init__(self,dir,vid):
        Thread.__init__(self)
        self.dir = dir
        self.vid = vid
        self.start()
        
    def run(self):
        self.sendVideo(self.dir,self.vid)
        return
    
    def getFile(self):
        return self.vid
    
    def sendVideo(self,dir,file):
        ftp = FTP()
        ftp.connect(ftp_host,ftp_port)
        ftp.login(ftp_user, ftp_pass)
        ftp.storbinary('STOR {0}'.format(file),open(os.path.join(dir,file),'rb'))
    

class EncoderApp(wx.App):
    def OnInit(self):
        frame = EncoderFrame(None,-1,'Clustered Handbrake',wx.DefaultPosition,wx.Size(800,550))
        frame.Show(True)
        self.SetTopWindow(frame)
        return True

def main():
    wxobj = EncoderApp(False)
    wxobj.MainLoop()
    

if __name__ == '__main__':
    main()
