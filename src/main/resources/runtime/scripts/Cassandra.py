import os
import time
import sys
import os.path
import stat
import re
import distutils.dir_util
from subprocess import call
from distutils import dir_util
from distutils import file_util
import stat
from datetime import datetime

from jarray import array

from java.lang import String
from java.lang import Object
from java.lang import Boolean
from java.lang import System
from java.util import Hashtable
from java.util import Set
from java.net import InetAddress

from javax.management import MBeanServerConnection
from javax.management import ObjectName
from javax.management.remote import JMXConnector
from javax.management.remote import JMXConnectorFactory
from javax.management.remote import JMXServiceURL

from com.datasynapse.fabric.util import ContainerUtils
from com.datasynapse.fabric.container import Feature
from com.datasynapse.fabric.common import RuntimeContextVariable


class CassandraNode:
    def __init__(self, additionalVariables):
        " initialize cassandra node"
        
        self.__seedConfigDir = getVariableValue("SEED_CONFIG_DIR")
        if not self.__seedConfigDir:
            raise Exception("Seed config directory is required")
        
        self.__seedConfigDir = os.path.join(self.__seedConfigDir, self.__getUniqueName())
        
        self.__locked = None
        self.__cluster = getVariableValue("CLUSTER_NAME")
        
        self.__lockExpire = int(getVariableValue("LOCK_EXPIRE", "300000"))
        self.__lockWait = int(getVariableValue("LOCK_WAIT", "30000"))
        self.__staleWait = int(getVariableValue("STALE_CONFIG_WAIT", "300"))
        self.__readConifgMax = int(getVariableValue("READ_CONFIG_MAX", "5"))
        self.__readConifgWait = int(getVariableValue("READ_CONFIG_WAIT", "30"))
        
        self.__getSeeds(additionalVariables)
        
        self.__initDirs(additionalVariables)
        
        jmxConfigFile = getVariableValue("JMX_CONFIG_FILE")
        javaOpts = getVariableValue("JVM_OPTS")
        if not javaOpts:
            javaOpts = "-server"
            
        javaOpts = javaOpts + " -Djava.io.tmpdir=" + self.__tmpdir + " -Dcom.sun.management.config.file=" + jmxConfigFile
        additionalVariables.add(RuntimeContextVariable("JVM_OPTS", javaOpts, RuntimeContextVariable.ENVIRONMENT_TYPE))
        additionalVariables.add(RuntimeContextVariable("RESTART_ENGINE_ON_DEACTIVATION", "true", RuntimeContextVariable.STRING_TYPE))
      
        # initialize JMX variables
        self.__jmxUrl = getVariableValue("JMX_URL")
        self.__jmxUser = getVariableValue("JMX_USERNAME")
        self.__jmxPassword = getVariableValue("JMX_PASSWORD")
        self.__jmxConnection = None
        self.__jmxConnector = None
        
        # initialize common variables
        self.__startWait = int(getVariableValue("START_POLL_PERIOD", "30000"))/1000
        self.__maxRestart = int(getVariableValue("MAX_RESTART", "10"))
        self.__restartTry = 0
        self.__restarting = None
        self.__shuttingDown = None
        
        self.__storageServiceMBean = ObjectName("org.apache.cassandra.db:type=StorageService")
     
        self.__readLatencyMBean = ObjectName("org.apache.cassandra.metrics:type=ClientRequest,scope=Read,name=Latency")
        self.__writeLatencyMBean = ObjectName("org.apache.cassandra.metrics:type=ClientRequest,scope=Write,name=Latency")
        self.__commitLogMBean = ObjectName("org.apache.cassandra.db:type=Commitlog")
        self.__compactionMgrMBean = ObjectName("org.apache.cassandra.db:type=CompactionManager")
        
        self.__statAttr = {"Read Latency Mean":"Mean",
                            "Write Latency Mean":"Mean",
                            "Storage Load": "Load",
                            "Active Count":"ActiveCount",
                            "Pending Tasks":"PendingTasks",
                            "Completed Tasks": "CompletedTasks",
                            "Bytes Total In Progress": "BytesTotalInProgress",
                            "Bytes Compacted": "BytesCompacted"};
                            
        self.__statObject = {"Read Latency Mean":self.__readLatencyMBean,
                            "Write Latency Mean":self.__writeLatencyMBean,
                            "Storage Load": self.__storageServiceMBean,
                            "Active Count": self.__commitLogMBean, 
                            "Pending Tasks": self.__commitLogMBean,
                            "Completed Tasks": self.__commitLogMBean,
                            "Bytes Total In Progress": self.__compactionMgrMBean,
                            "Bytes Compacted": self.__compactionMgrMBean};
        
     
        self.__jmxPort = getVariableValue("RMI_REGISTRY_PORT")
        self.__pid = None
        self.__initalized = False


    def __getUniqueName(self):
        "get a unique name"
       
        name = proxy.container.currentDomain.name
        slen = len(name)
        name = name.replace(" ", "")
        name = name.replace(".", "")
        name = name.replace("_", "")
        name = name.replace("-", "")
        
        name = name + `slen`
        return name


    def __getSeeds(self, additionalVariables):
        "get seeds information"
     
        self.__listenAddress = getVariableValue("LISTEN_ADDRESS")
        self.__minSeedNodes = int(getVariableValue("MIN_SEED_NODES"))
            
        if self.__minSeedNodes < 1:
            self.__minSeedNodes = 1
                
        attempt = 0
        
        seedList = []
        while len(seedList) < self.__minSeedNodes and attempt < self.__readConifgMax:
            attempt = attempt + 1
            
            try:
                self.__lock()
                mkdir_p(self.__seedConfigDir, 0777)
                self.__seedFile = os.path.join(self.__seedConfigDir, "seed." + self.__listenAddress )
                self.__writeConfig(self.__seedFile, self.__listenAddress )
           
                count = 0
                list = os.listdir(self.__seedConfigDir)
                for entry in list:
                
                    path = os.path.join(self.__seedConfigDir, entry)
                    if time.time() - os.path.getmtime(path) > self.__staleWait:
                        logger.info("Removing stale server configuration file:" + path)
                        os.remove(path)
                    else:
                        seed = self.__readConfig(path)
                        if seed and seed not in seedList:
                            seedList.append(seed)
                        if len(seedList) == self.__minSeedNodes:
                            break
            
                self.__unlock()
                
            
            finally:
                self.__unlock()
            
            if len(seedList) < self.__minSeedNodes and attempt < self.__readConifgMax:
                    time.sleep(self.__readConifgWait)
           
        if len(seedList) < self.__minSeedNodes:
            raise Exception("Minimum number seeds not found:" + `self.__minSeedNodes` + ":" + self.__seedConfigDir)
        
        seedList.sort()
        self.__seeds = seedList
        seeds = None
        for s in self.__seeds:
            if seeds:
                seeds = seeds + "," +s
            else:
                seeds = s
                
        additionalVariables.add(RuntimeContextVariable("SEEDS", seeds, RuntimeContextVariable.STRING_TYPE, ""))
            
    def __initDirs(self, additionalVariables ):
        "init data dirs"
        
        dir = getVariableValue("DATA_FILE_DIRECTORIES")
        workDir = getVariableValue("ENGINE_WORK_DIR")
        self.__persistent = False
        dataDirs = ""
        dirList = dir.split(",")
        for dir in dirList:
            dir = dir.strip()
            if len(dataDirs) > 0:
                dataDirs = dataDirs + "\n" + "- " + dir
            else:
                dataDirs = "- " + dir
            mkdir_p(dir)
            if not re.search("^" + workDir + "*", dir):
                    logger.info("Using persistent data dir:" + dir)
                    self.__persistent = True
                    
        additionalVariables.add(RuntimeContextVariable("DATA_FILE_DIRECTORIES", dataDirs, RuntimeContextVariable.STRING_TYPE))
        
        dir = getVariableValue("COMMIT_LOG_DIRECTORY")
        mkdir_p(dir)
        
        dir = getVariableValue("SAVED_CACHES_DIRECTORY")
        mkdir_p(dir)
        
        dir = getVariableValue("CASSANDRA_LOG_DIRECTORY")
        mkdir_p(dir)
        
        home = getVariableValue("CASSANDRA_HOME")
        dir = os.path.join(home, "bin")
        changePermissions(dir)
        self.__cassandra = os.path.join(dir, "cassandra")
                
        self.__tmpdir = os.path.join(home, "tmp")
        mkdir_p(self.__tmpdir)
        
        self.__startWait = int(getVariableValue("START_POLL_PERIOD", "30000"))/1000
        self.__maxRestart = int(getVariableValue("MAX_RESTART", "10"))
        self.__lockExpire = int(getVariableValue("LOCK_EXPIRE", "300000"))
        self.__lockWait = int(getVariableValue("LOCK_WAIT", "30000"))
     
        
    def __createJMXConnection(self):
        "create JMX connection"
        
        self.__jmxConnection = None
        self.__jmxConnector = None
        
        try:
            jmxServiceUrl = JMXServiceURL(self.__jmxUrl)
            env = Hashtable()
            cred = array([self.__jmxUser, self.__jmxPassword], String)
            env.put("jmx.remote.credentials", cred)
            logger.info("Connecting to node JVM via JMX:" + `jmxServiceUrl`)
            self.__jmxConnector = JMXConnectorFactory.connect(jmxServiceUrl, env)
            self.__jmxConnection = self.__jmxConnector.getMBeanServerConnection()
            logger.info("Successfully connected to Node JVM via JMX:" + `jmxServiceUrl`)
            
             
        except:
            type, value, traceback = sys.exc_info()
            logger.fine("JMX Connection error:" + `value`)
            self.__jmxConnection = None
            try:
                if self.__jmxConnector:
                    self.__jmxConnector.close()
                    self.__jmxConnector = None
                    self.__jmxConnection = None
            except:
                type, value, traceback = sys.exc_info()
                logger.fine("JMX Connector close error:" + `value`)
        
   
    def __lock(self):
        "get global lock"
        self.__locked = ContainerUtils.acquireGlobalLock(self.__cluster, self.__lockExpire, self.__lockWait)
        if not self.__locked:
            raise Exception("Unable to acquire global lock:" + self.__cluster)
    
    def __unlock(self):
        "unlock global lock"
        if self.__locked:
            ContainerUtils.releaseGlobalLock(self.__cluster)
            self.__locked = None
    
    def isNodeRunning(self):
        " is node running"
        
        if self.__restarting:
            return True
        
        running = False
        try:
            running = self.__jmxConnection.getAttribute(self.__storageServiceMBean, "RPCServerRunning")
        except:
            type, value, traceback = sys.exc_info()
            logger.fine("is Node running error:" + `value`)
                
        if not running and not self.__shuttingDown:
            running = self.__restart()
            
        return running
      
      
    def __writeConfig(self, path, seedConfig):
        "write server config"
        
        file = None
        try:
            file = open(path, "w")
            file.write(seedConfig + "\n")
        finally:
            if file:
                file.close()
    
    def __readConfig(self, path):
        "read server config information from file"
        file = None
        seedConfig = None
        try:
            if os.path.isfile(path):
                file = open(path, "r")
                lines = file.readlines()
                for line in lines:
                    seedConfig = line.strip()
                    break;
        finally:
            if file:
                file.close()
                
        return seedConfig          
    
    def __restart(self):
        "restart node"
        
        logger.info("Restarting server")
        restarted = False
        self.__restarting = True
        while not restarted and self.__restartTry < self.__maxRestart:
            self.__restartTry = self.__restartTry + 1
            
            try:
                self.__lock()
                self.__killProcess()
                self.startNode()
                self.__unlock()
                
                attempt = 0
                while not restarted and attempt < self.__readConifgMax:
                    attempt = attempt + 1
                    time.sleep(self.__startWait) # wait for the server to start
                    restarted = self.hasNodeStarted()
                    
                if restarted:
                    logger.info("Successfully restarted server")
                
            except:
                type, value, traceback = sys.exc_info()
                logger.fine("restart error:" + `value`)
            finally:
                
                self.__unlock()
        
        self.__restarting = False
        return restarted
        
    
    def __killProcess(self):
        "kill running process"
    
        if self.__pid:
            logger.info("kill Casandra process:" + self.__pid)
            call(["kill", "-9", self.__pid])
            self.__pid = None
                    
    def hasNodeStarted(self):
        " has node started"
        
        started = False
        
        if self.__jmxConnection == None:
            self.__createJMXConnection()
        else:
            logger.info("JMX connection:" + `self.__jmxConnection`)
        try:
            if self.__jmxConnection:
                self.__unlock()
                self.__runtimeMBean = ObjectName("java.lang:type=Runtime")
                name = self.__jmxConnection.getAttribute(self.__runtimeMBean, "Name")
                self.__pid = name.split("@")[0]
                logger.info("Cassandra process id is:" + self.__pid)
                self.__initalized = self.__jmxConnection.getAttribute(self.__storageServiceMBean, "Initialized")
                if self.__initalized:
                    logger.info("Node has initialized")
                    joined = self.__jmxConnection.getAttribute(self.__storageServiceMBean, "Joined")
                    if joined:
                        liveNodes = self.__jmxConnection.getAttribute(self.__storageServiceMBean, "LiveNodes")
                        liveSeedNodes = []
                        for node in liveNodes:
                           if node in self.__seeds:
                               liveSeedNodes.append(node)
                               if len(liveSeedNodes) == len(self.__seeds):
                                   logger.info("Node has joined the cluster with seeds:" + `self.__seeds`)
                                   self.__initNodeInfo()
                                   started = True
                                   break
        except:
            type, value, traceback = sys.exc_info()
            
            if self.__initalized:
                logger.fine("Has node started error:" + `value`) 
        
                self.__killProcess()
                raise Exception("Could not join cluster ring")
              
        return started

    def __initNodeInfo(self):
        "init info about node"
        
        try:
            self.__tokens = self.__jmxConnection.getAttribute(self.__storageServiceMBean, "Tokens")
            self.__localHostId = self.__jmxConnection.getAttribute(self.__storageServiceMBean, "LocalHostId")
        except:
            type, value, traceback = sys.exc_info()
            logger.fine("initNodeInfo error:" + `value`) 
        
    def startNode(self):
        "start node"
        
        self.__jmxConnection = None
        self.__jmxConnector = None
        
        path = os.path.join(getVariableValue("CASSANDRA_HOME"), "management", "jmxremote.password")
        logger.info("Restrict read write access:" + path)
        os.chmod(path, stat.S_IRUSR)
        
        unixCommand = proxy.container.getUnixCommand()
        unixCommand.setStartupCommand(self.__cassandra)
        
        windowsCommand = proxy.container.getWindowsCommand()
        windowsCommand.setStartupCommand(self.__cassandra +".bat")
        self.__lock()
        proxy.doStart()
    
    def shutdownNode(self):
        "shutdown node"
        try:
            self.__shuttingDown = True
            self.__lock()
            os.remove(self.__seedFile)
            oa = array([], Object)
            sa = array([], String)
            logger.info("Drain node")
            self.__jmxConnection.invoke(self.__storageServiceMBean, "drain", oa, sa)
            self.__jmxConnection.invoke(self.__storageServiceMBean, "stopGossiping", oa, sa)
        except:
            type, value, traceback = sys.exc_info()
            logger.fine("shutdown node error:" + `value`)
        finally:
            self.__unlock()
            self.__killProcess()
            self.__jmxConnection = None
            try:
                if self.__jmxConnector:
                    self.__jmxConnector.close()
                    self.__jmxConnector = None
                    self.__jmxConnection = None
            except:
                type, value, traceback = sys.exc_info()
                logger.fine("shutdown node error:" + `value`)
        proxy.doShutdown()

    
    def installActivationInfo(self, info):
        "install activation info"

   
        try:
            propertyName = "RPC Port"
            propertyValue = getVariableValue("RPC_PORT")
            logger.info("setting property:" + propertyName +":"+ propertyValue)
            info.setProperty(propertyName, propertyValue)
        
            propertyName = "Tokens"
            logger.info("setting property:" + propertyName +":"+ `self.__tokens`)
            info.setProperty(propertyName, `self.__tokens`)
        
            propertyName = "Primary Range"
            propertyValue = self.__jmxConnection.getAttribute(self.__storageServiceMBean, "PrimaryRange")
            logger.info("setting property:" + propertyName +":"+ `propertyValue`)
            info.setProperty(propertyName, `propertyValue`)
        
            propertyName = "LocalHostId"
            logger.info("setting property:" + propertyName +":"+ self.__localHostId)
            info.setProperty(propertyName, self.__localHostId)
                
        except:
            type, value, traceback = sys.exc_info()
            logger.fine("install activation info error:" + `value`)
                   
    def getStatistic(self, statName):
        " get statistic"
        
        attrName = self.__statAttr[statName]
        objectName = self.__statObject[statName]
        
        value = self.__jmxConnection.getAttribute(objectName, attrName)
        return value

def mkdir_p(path, mode=0700):
    if not os.path.isdir(path):
        logger.info("Creating directory:" + path)
        os.makedirs(path, mode)
    
def changePermissions(dir):
    logger.info("chmod:" + dir)
    os.chmod(dir, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
      
    for dirpath, dirnames, filenames in os.walk(dir):
        for dirname in dirnames:
            dpath = os.path.join(dirpath, dirname)
            os.chmod(dpath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
           
        for filename in filenames:
               filePath = os.path.join(dirpath, filename)
               os.chmod(filePath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

def copyContainerEnvironment():
    " copy container environment"
    
    count = runtimeContext.variableCount
    for i in range(0, count, 1):
        rtv = runtimeContext.getVariable(i)
        if rtv.type == "Environment":
            os.environ[rtv.name] = rtv.value
              
def getVariableValue(name, value=None):
    "get runtime variable value"
    var = runtimeContext.getVariable(name)
    if var != None:
        value = var.value
    
    return value

def doInit(additionalVariables):
    "do init"
    cassandraNode = CassandraNode(additionalVariables)
             
    cassandraNodeRcv = RuntimeContextVariable("CASSANDRA_NODE_OBJECT", cassandraNode, RuntimeContextVariable.OBJECT_TYPE)
    runtimeContext.addVariable(cassandraNodeRcv)
    
def doStart():
    "do start"
    logger.info("Enter CassandraContainer:doStart")
    cassandraNode = getVariableValue("CASSANDRA_NODE_OBJECT")
        
    if cassandraNode:
        cassandraNode.startNode()
        
    logger.info("Exit CassandraContainer:doStart")

def doShutdown():
    "do shutdown"
    logger.info("Enter CassandraContainer:doShutdown")
    try:
        cassandraNode = getVariableValue("CASSANDRA_NODE_OBJECT")
        if cassandraNode:
            cassandraNode.shutdownNode()
    except:
        type, value, traceback = sys.exc_info()
        logger.severe("CassandraContainer:doShutdown:JMX Shutdown error:" + `value`)
    
    logger.info("Exit CassandraContainer:doShutdown")

def hasContainerStarted():
    logger.info("Enter CassandraContainer:hasContainerStarted")
    started = False
    cassandraNode = getVariableValue("CASSANDRA_NODE_OBJECT")
        
    if cassandraNode:
        started = cassandraNode.hasNodeStarted()
            
    logger.info("Exit CassandraContainer:hasContainerStarted")
    return started
    
def isContainerRunning():
    running = False
    try:
        cassandraNode = getVariableValue("CASSANDRA_NODE_OBJECT")
        if cassandraNode:
            running = cassandraNode.isNodeRunning()
    except:
        type, value, traceback = sys.exc_info()
        logger.severe("Unexpected error in CassandraContainer:isContainerRunning:" + `value`)
    
    return running

def doInstall(info):
    " do install of activation info"

    logger.info("CassandraContainer: doInstall:Enter")
    try:
       cassandraNode = getVariableValue("CASSANDRA_NODE_OBJECT")
       if cassandraNode:
            cassandraNode.installActivationInfo(info)
    except:
        type, value, traceback = sys.exc_info()
        logger.severe("Unexpected error in CassandraContainer:doInstall:" + `value`)
        
    logger.info("CassandraContainer: doInstall:Exit")
    
def getStatistic(statName):
    stat = None
    try:
        cassandraNode = getVariableValue("CASSANDRA_NODE_OBJECT")
        stat = cassandraNode.getStatistic(statName)
    except:
        type, value, traceback = sys.exc_info()
        logger.severe("Unexpected error in CassandraContainer:getStatistic:" + `value`)
    return stat

def getContainerStartConditionPollPeriod():
    poll = getVariableValue("START_POLL_PERIOD", "10000")
    return int(poll)
    
def getContainerRunningConditionPollPeriod():
    poll = getVariableValue("RUNNING_POLL_PERIOD", "60000")
    return int(poll)

