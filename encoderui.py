#!/usr/bin/python

import wx
import wx.grid
import wx.lib.agw.aui as aui
import Pyro4
import os
import threading
from encoder_cfg import pyro_host, pyro_port, ftp_host, ftp_port, ftp_user, ftp_pass
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

        #Mapping to keep track of which task occupies which row
        self.rowMapping = {}
        
        self.rowLabels = rowLabels
        self.colLabels = colLabels

    def sortData(self,data):
        # Sorting goes Encoding Tasks > Pending Tasks > Finished > Cancelled > Error
        # Tasks in the same state are then compared by the datetime they were added
        # to the server.
        data =  sorted(data, key=lambda x: statusMapping[x[1]]+str(x[6]))
        return data
        
    def updateData(self,data,grid):
        # Old number of rows
        start = len(self.data)

        # New number of rows
        end = len(data)

        # Names we actually hit this time -- used to delete old references later
        updatedNames = []

        # Currently selected tasks in the table
        selectedNames = []
        for row in grid.GetSelectedRows():
            selectedNames.append(self.data[row][0])

        data = self.sortData(data)

        # Batch mode ensures all updates happen at once
        grid.BeginBatch()

        # Map each row from the new data object onto the current data object
        # and set the corresponding values on the wx.Grid
        for row, info in enumerate(data):
            updatedNames.append(info[0])
            if row < len(self.data):
                # Nothing has changed, don't waste cycles remapping the same data
                if data[row] == self.data[row]:
                    continue
            self.rowMapping[info[0]] = row
            # We're short some rows, append the data instead of mapping
            if row >= len(self.data):
                self.data.append(info)
            else:
                self.data[row] = info
            # Map this row onto the grid
            for i in xrange(0,6):
                self.SetValue(row,i,info[i])
        # Grid updates done, end the batch
        grid.EndBatch()

        # Delete unused references in the rowMapping dictionary
        for name in self.rowMapping.keys():
            if name not in updatedNames:
                del self.rowMapping[name]

        # Clear selection and reselect any previously selected
        # tasks which still exist somewhere in the grid
        grid.ClearSelection()
        for name in selectedNames:
            if name in self.rowMapping:
                grid.SelectRow(self.rowMapping[name],True)

        # We've got too many rows, inform the grid that it needs to delete some
        if end < start:
            for row in xrange(end,start):
                del self.data[row]
            msg = wx.grid.GridTableMessage(self,wx.grid.GRIDTABLE_NOTIFY_ROWS_DELETED,end,start-end)
            grid.ProcessTableMessage(msg)

        # We're short one or more rows, inform the grid it needs to add some
        elif end > start:
            msg = wx.grid.GridTableMessage(self,wx.grid.GRIDTABLE_NOTIFY_ROWS_APPENDED,end-start)
            grid.ProcessTableMessage(msg)
            
    def GetNumberRows(self):
        return len(self.data)
    
    def GetNumberCols(self):
        return len(self.colLabels)
        
    def GetColLabelValue(self,col):
        if self.colLabels:
            return self.colLabels[col]
    
    def GetRowLabelValue(self,row):
        if self.rowLabels:
            return self.rowLabels[row]
        return ''
        
    def IsEmptyCell(self,row,col):
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

    
class TaskGrid(wx.grid.Grid):
    def __init__(self,parent,data,rowLabels=None,colLabels=None):
        wx.grid.Grid.__init__(self,parent,-1)
        self.rowLabels = rowLabels
        self.colLabels = colLabels

        # We don't give the table the data initially as all the logic
        # for correctly sorting + mapping is in the setdata function
        self.SetTable(TaskTable([],self.rowLabels,self.colLabels))
        self.SetData(data)

        # TODO -- Revisit these sizes, kind of ugly on Linux
        self.SetColSize(0,300)
        self.SetColSize(1,50)
        self.SetColSize(2,150)
        self.SetColSize(3,70)
        self.SetColSize(4,150)
        self.SetColSize(5,150)

        # We have no row labels and they take up a good amount of space by default
        self.SetRowLabelSize(0)

        # You cannot edit, you lose, good day, sir.
        self.EnableEditing(False)

        # This will select whole rows at a time, which makes sense for our needs
        # since each row is a task and tasks are the atomic unit
        self.SetSelectionMode(1)
        
    def getRows(self,rows):
        return self.GetTable().getRows(rows)
        
    def SetData(self,data):
        self.GetTable().updateData(data,self)
        # Grid will not reflect changes made until forcerefresh is called
        self.ForceRefresh()

class taskViewDialog(wx.Dialog):
    """ A quick dialog to that gives a detailed view of selected task(s)
        This view provides extra data compared to that displayed directly
        in the table:
            - encoder
            - large file support
            - quality setting
            - format
            - Task added datetime
    """
    def __init__(self,parent,rows,table):
        self._parent = parent
        self._table = table
        self.rows = rows

        # Nothing to show, just quit
        if not rows or not table:
            self.Close()

        # Grab the selected rows from the table so we know what to display
        rows = table.getRows(rows)
        tasks = []

        # Grab the global list of tasks from the central server
        # TODO -- This is a little hackish, maybe the table could
        # hold a mapping that contains the actual task objects
        # that way we could avoid the extra call to the server
        # which is already happening every few seconds anyway
        tasksIn = self._parent.central.getTasks()

        # Grab the task objects matching the selected rows
        for row in rows:
            if row[0] in tasksIn:
                tasks.append(row[0])

        # Got no tasks, they may have been removed, either way
        # we've got nothing, close 'er up
        if not tasks:
            self.Close()
        label = 'Detailed Task View'
        wx.Dialog.__init__(self,parent,-1,label,wx.DefaultPosition,wx.Size(310,400))

        mainBox = wx.BoxSizer(wx.VERTICAL)

        # TODO -- Sizing is ugly in Linux
        self.taskChooser = wx.ListBox(self,-1,style=wx.LB_HSCROLL|wx.LB_SINGLE,size=wx.Size(250,100))

        # General Task Info
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
        ### HB Settings
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
        # Which task is selected?
        id = self.tasks[self.taskChooser.GetSelection()]
        task,encoder,status = self.tasksIn[id]

        # Display task's info
        self.taskName.SetLabel('\n'.join(textwrap.wrap(id,35)))
        if task.getOutputName():
            self.taskOutName.SetLabel('\n'.join(textwrap.wrap(task.getOutputName(),35)))
        self.taskAdded.SetLabel(str(task.getAdded()))
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
    """ A quick dialog for adding new encode tasks to the server
        Allows you to add multiple videos at once and specify
        a few HB encoding settings -- just a few for now
    """
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
        # TODO -- This currently clears out any videos already selected, it would probably
        # make more sense for this to just append -- the clear button should handle clearing
        # TODO -- Get a more extensive list of support videos based on HB support and add it to one
        # file that's just called Video Files
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
        """ populates the listbox with the current list of added video files """
        self.vidBox.Clear()
        for item in self.vids:
            self.vidBox.Insert(item,0,None)

class EncoderFrame(wx.Frame):
    """ The Main UI element
    """
    def __init__(self,parent,ID,title,position,size):
        wx.Frame.__init__(self,parent,ID,title,position,size)
        self.mgr = aui.AuiManager(self)
        taskPanel = wx.Panel(self,-1,size=(350,300))
        taskBox = wx.BoxSizer(wx.VERTICAL)

        # Check in with the central dispatch (should be defined in encoder_cfg.py)
        # if you aren't running a server, terrible things will happen here
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

        # Our working dialog for display when we're busy FTP'ing files around
        self.workingDiag = None

        # Thread reference to the thread which will perform the actual FTP operations
        self.currThread = None

        # Counts the videos we've FTP'ed so far -- assuming we've added multiple videos
        self.workingTotal = 0

        # Would be used for cancelling adding -- if that were implemented
        # TODO -- Implement cancelling of FTP / Add Task Operation
        self.needCancel = False

        # List of video files we still need to FTP and add tasks for
        self.pendingSends = []

        # The main table display which contains all the tasks
        self.taskList = TaskGrid(taskPanel,self.getData(),rowLabels=None,colLabels=['Task Name','Status','Assigned Encoder','Completed','Started','Finished'])
        
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

        # This timer will update the table with the latest and greatest list of tasks
        # from the central server every 4000ms
        self.timer = wx.Timer(self,self.ids['taskTimer'])
        self.timer.Start(4000)
        
        wx.EVT_TIMER(self,self.ids['taskTimer'],self.refreshList)
        wx.EVT_TOOL(self,self.ids['cancel'],self.cancel)
        wx.EVT_TOOL(self,self.ids['add'],self.add)
        wx.EVT_TOOL(self,self.ids['view'],self.view)
        wx.EVT_TOOL(self,self.ids['clear'],self.clear)
        wx.EVT_TOOL(self,self.ids['retry'],self.retry)
        self.taskList.Bind(wx.grid.EVT_GRID_CELL_LEFT_CLICK,self.handleClick)

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
        """ Kick off the first FTP thread and show a progress dialog
        """
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
        """ Used for calculating Grid selections
            since the grid selection model, even
            when using row only selection, completely
            sucks """
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
        """ Custom click handling for the wx.Grid so
            rows are actually selected when you click
            on them
        """

        #TODO -- Make shift-clicking perform more like you'd expect
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
        """ Clear selected non-active/pending tasks from the table & central server
        """
        for task in self.taskList.getRows((self.taskList.GetSelectedRows())):
            if task[1] in ['Cancelled','Error','Finished']:
                if not self.central.clearTask(task[0]):
                    wx.MessageBox('Could not clear task, was it removed?','Error',style=wx.OK|wx.ICON_WARNING)
                    break
            else:
                wx.MessageBox('Can only clear cancelled, error\'ed, or finished tasks.','Error',style=wx.OK|wx.ICON_WARNING)
                break
        
    def cancel(self,evt):
        """ Cancel selected pending/active tasks from the server
        """
        for task in self.taskList.getRows(self.taskList.GetSelectedRows()):
            if task[1] in ['Pending','Encoding']:
                if not self.central.cancelTask(task[0]):
                    wx.MessageBox('Could not cancel task, did it finish already?','Error',style=wx.OK|wx.ICON_WARNING)
                    break
            else:
                wx.MessageBox('Can only cancel pending or encoding tasks.','Error',style=wx.OK|wx.ICON_WARNING)
                break

    def retry(self,evt):
        """
            Retry selected errored or cancelled tasks
        """
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
    
    def threadDone(self,settings,vid,evt=None):
        """
            Called by FTP thread upon completion, if we have more videos to send
            kick off the next thread and update the progress dialog so the user knows
            what's going on
        """
        # TODO -- This is where we need to check for a signal that a cancellation has been requested
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
        """
            Fire up an FTP connection to the central server
            and upload the videos from the localhost that need
            to be encoded
        """
        ftp = FTP()
        ftp.connect(ftp_host,ftp_port)
        ftp.login(ftp_user, ftp_pass)
        if not dir.endswith(os.sep):
            dir += os.sep
        ftp.storbinary('STOR {0}'.format(vid),open(os.path.join(dir,vid),'rb'))
        wx.CallAfter(self.threadDone,settings,vid)
    
    def getData(self):
        """
            Grab the list of tasks from the central server and put them into a more
            grid friendly form factor
        """
        tasks = self.central.getTasks()
        data = []
        for task,name,status in tasks.values():
            row = [task.getName(),status,name,str(task.getCompleted()),task.getStarted() or ' ',task.getFinished() or ' ',task.getAdded()]
            data.append(row)
        return data

    def refreshList(self,evt=None):
        """
            Push the latest task info to the grid
        """
        self.taskList.SetData(self.getData())

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
