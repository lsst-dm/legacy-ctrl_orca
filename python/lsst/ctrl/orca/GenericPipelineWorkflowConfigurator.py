# 
# LSST Data Management System
# Copyright 2008, 2009, 2010 LSST Corporation.
# 
# This product includes software developed by the
# LSST Project (http://www.lsst.org/).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the LSST License Statement and 
# the GNU General Public License along with this program.  If not, 
# see <http://www.lsstcorp.org/LegalNotices/>.
#

import sys,os, os.path, shutil, sets, stat
import lsst.ctrl.orca as orca
import lsst.pex.config as pexConfig

from lsst.pex.harness.Directories import Directories
from lsst.pex.logging import Log

from lsst.ctrl.orca.EnvString import EnvString
from lsst.ctrl.orca.WorkflowConfigurator import WorkflowConfigurator
from lsst.ctrl.orca.GenericPipelineWorkflowLauncher import GenericPipelineWorkflowLauncher
from lsst.ctrl.orca.GenericFileWaiter import GenericFileWaiter

##
#
# GenericPipelineWorkflowConfigurator 
#
class GenericPipelineWorkflowConfigurator(WorkflowConfigurator):
    def __init__(self, runid, repository, prodConfig, wfConfig, logger):
        self.logger = logger
        self.logger.log(Log.DEBUG, "GenericPipelineWorkflowConfigurator:__init__")
        self.runid = runid
        self.prodConfig = prodConfig
        self.wfConfig = wfConfig
        self.repository = repository

        self.wfVerbosity = None

        self.nodes = None
        self.directories = None
        self.dirs = None
        self.defaultRunDir = None
        self.logFileNames = []
        self.pipelineNames = []
        self.eventBrokerHost = None

    ##
    # @brief Setup as much as possible in preparation to execute the workflow
    #            and return a WorkflowLauncher object that will launch the
    #            configured workflow.
    # @param provSetup
    # @param wfVerbosity
    #
    def configure(self, provSetup, wfVerbosity):
        self.wfVerbosity = wfVerbosity
        self._configureDatabases(provSetup)
        return self._configureSpecialized(provSetup, self.wfConfig)
    ##
    # @brief Setup as much as possible in preparation to execute the workflow
    #            and return a WorkflowLauncher object that will launch the
    #            configured workflow.
    # @param provSetup provenance info
    # @param wfConfig the workflow config to use for configuration
    #
    
    def _configureSpecialized(self, provSetup, wfConfig):
        self.logger.log(Log.DEBUG, "GenericPipelineWorkflowConfigurator:configure")
        self.shortName = wfConfig.shortName

        filename = wfConfig.platform
        platformConfig = Platform()
        platformConfig.load(filename)

        self.defaultDomain = platformConfig.deploy.defaultDomain
        pipelineConfig = wfConfig.pipeline
        expandedPipelineConfigs = self.expandConfigs(self.shortName, pipelineConfig)
        #launchCmd = {}
        launchCmd = []
        for pipelineConfigGroup in expandedPipelinePolicies:
            pipelineConfig = pipelineConfigGroup.getConfigName()
            num = pipelineConfigGroup.getConfigNumber()

            self.nodes = self.createNodeList(pipelineConfig)
            self.createDirs(platformConfig, pipelineConfig)
            pipelineShortName = pipelineConfig.shortName
            launchName = "%s_%d" % (pipelineShortName, num)
            self.logger.log(Log.DEBUG, "GenericPipelineWorkflowConfigurator: launchName = %s" % launchName)
            val = self.deploySetup(provSetup, wfConfig, platformConfig, pipelineConfigGroup)
            launchCmd.append(val)
            self.logger.log(Log.DEBUG, "launchCmd = %s" % launchCmd)
        self.deployData(wfConfig)

        fileWaiter = GenericFileWaiter(self.logFileNames, self.logger)
        workflowLauncher = GenericPipelineWorkflowLauncher(launchCmd, self.prodConfig, wfConfig, self.runid, fileWaiter, self.pipelineNames, self.logger)
        return workflowLauncher

    ##
    # @brief creates a list of nodes from platform.deploy.nodes
    # @return the list of nodes
    #
    def createNodeList(self,  pipelineConfig):
        self.logger.log(Log.DEBUG, "GenericPipelineWorkflowConfigurator:createNodeList")
        node = pipelineConfig.deploy.processesOnNode

        nodes = map(self.expandNodeHost, node)
        # by convention, the master node is the first node in the list
        # we use this later to launch things, so strip out the info past ":", if it's there.
        self.masterNode = nodes[0]
        colon = self.masterNode.find(':')
        if colon > 1:
            self.masterNode = self.masterNode[0:colon]
        return nodes

    def getWorkflowName(self):
        return self.workflow
    
    def getNodeCount(self):
        return len(self.nodes)

    def deployData(self, wfConfig):
        self.logger.log(Log.DEBUG, "GenericPipelineWorkflowConfigurator:deployData")

        # add data deploy here

        if wfConfiguration.configuration["generic"] != None:
            configuration = wfConfig.configuration["generic"]
            if configuration.deployData != None:
                deployConfig = configuration.deployData
                dataRepository = deployConfig.dataRepository
                dataRepository = EnvString.resolve(dataRepository)
                deployScript = deployConfig.script
                deployScript = EnvString.resolve(deployScript)
                collection = deployConfig.collection
                
                if os.path.isfile(deployScript) == True:
                    runDir = self.directories.getDefaultRunDir()
                    deployCmd = [deployScript, runDir, dataRepository, collection]
                    print ">>> ",deployCmd
                    pid = os.fork()
                    if not pid:
                        os.execvp(deployCmd[0], deployCmd)
                    os.wait()[0]
                else:
                    self.logger.log(Log.DEBUG, "GenericPipelineWorkflowConfigurator:deployData: warning: script '%s' doesn't exist" % deployScript)
        # end data deploy here


    ##
    # @brief 
    #
    def deploySetup(self, provSetup, wfConfig, platformConfig, pipelineConfigGroup):
        self.logger.log(Log.DEBUG, "GenericPipelineWorkflowConfigurator:deploySetup")

        pipelineConfig = pipelineConfigGroup.getConfigName()
        shortName = pipelineConfig.shortName

        pipelineConfigNumber = pipelineConfigGroup.getConfigNumber()
        pipelineName = "%s_%d" % (shortName, pipelineConfigNumber)

        globalPipelineOffset = pipelineConfigGroup.getGlobalOffset()

        workDir = self.dirs.get("work")

        # create the subdirectory for the pipeline specific files
        logDir = os.path.join(self.dirs.get("work"), pipelineName)
        if not os.path.exists(logDir):
            os.makedirs(logDir)


        self.pipelineNames.append(pipelineName)

        # create the list of launch.log files we'll watch for later.
        logFile = os.path.join(pipelineName, "launch.log")
        logFile = os.path.join(workDir, logFile)
        self.logFileNames.append(logFile)
        
        # TODO - write "getPath()
        filename = self.getPath(pipelineConfig.definition)
        fullpath = None
        if os.path.isabs(filename):
            fullpath = filename
        else:
            fullpath = os.path.join(self.repository, filename)

        # TODO - write object to load in definition file
        definitionConfig = PipelineDefinitionConfig(fullpath)
        if pipelineConfigNumber == 1:
            if platformConfig.dir != None:
                definitionConfig.execute.dir = platformConfig.dir
            if self.prodConfig.eventBrokerHost != None:
                self.eventBrokerHost = self.prodConfig.eventBrokerHost
                definitionConfig.execute.eventBrokerHost = self.eventBrokerHost
    
            if self.wfConfig.shutdownTopic != None:
                definitionConfig.execute.shutdownTopic = self.wfConfig.shutdownTopic
            if self.prodConfig.logThreshold != None:
                definitionConfig.execute.logThreshold = self.prodConfig.logThreshold
            newConfigFile = os.path.join(workDir, filename)

            # TODO
            pw =ConfigWriter(newConfigFile)
            pw.write(definitionConfig)
            pw.close()

            # copy the workerdone.py utility over to the work directory
            script = EnvString.resolve("$CTRL_ORCA_DIR/bin/workerdone.py")
            remoteName = os.path.join(workDir, os.path.basename(script))
            shutil.copyfile(script,remoteName)
            shutil.copystat(script,remoteName)

        # copy /bin/sh script responsible for environment setting

        setupPath = definitionConfig.framework.environment
        if setupPath:
            setupPath = EnvString.resolve(setupPath)        
        self.script = setupPath

        if orca.envscript is None:
            self.logger.log(self.logger.INFO-1, "Using configured setup.sh")
        else:
            self.script = orca.envscript
        if not self.script:
             raise RuntimeError("couldn't find framework.environment")

        # only copy the setup script once
        if pipelineConfigNumber == 1:
            shutil.copy(self.script, workDir)

        # now point at the new location for the setup script
        self.script = os.path.join(workDir, os.path.basename(self.script))

        #
        # Write all config files out to the work directory, 
        # but only do it once.
        
        if pipelineConfigNumber == 1:
        
            # first, grab all the file names, and throw them into a Set() to 
            # avoid duplication
            pipelineConfigSet = sets.Set()

            ConfigUtils.getAllFilenames(self.repository, definitionConfig, pipelineConfigSet)

            # Cycle through the file names, creating subdirectories as required,
            # and copy them to the destination directory
            for configFile in pipelineConfigSet:
                destName = configFile.replace(self.repository+"/","")
                tokens = destName.split('/')
                tokensLength = len(tokens)
                destinationFile = tokens[len(tokens)-1]
                destinationDir = workDir
                for newDestinationDir in tokens[:len(tokens)-1]:
                    newDir = os.path.join(workDir, newDestinationDir)
                    if os.path.exists(newDir) == False:
                        os.mkdir(newDir)
                    destinationDir = newDir
                shutil.copyfile(configFile, os.path.join(destinationDir, destinationFile))

        # create the launch command
        execPath = definitionConfig.framework.exec
        #execCmd = EnvString.resolve(execPath)
        execCmd = execPath

        #cmd = ["ssh", self.masterNode, "cd %s; source %s; %s %s %s -L %s" % (self.dirs.get("work"), self.script, execCmd, filename, self.runid, self.wfVerbosity) ]

        # write out the launch script
        # write out the script we use to kick things off
        launchName = "launch_%s.sh" % pipelineName

        name = os.path.join(logDir, launchName)


        launcher = open(name, 'w')
        launcher.write("#!/bin/sh\n")
        launcher.write("export SHELL=/bin/sh\n")
        launcher.write("cd %s\n" % self.dirs.get("work"))
        launcher.write("source %s\n" % self.script)
        launcher.write("eups list --setup 2>/dev/null >%s/eups-env.txt\n" % logDir)

        cmds = provSetup.getCmds()
        workflowConfigs = self.prodConfig.workflow


        # append the other information we previously didn't have access to, but need for recording.
        for cmd in cmds:
            wfShortName = wfConfig.get("shortName")
            cmd.append("--activityname=%s_%s" % (wfShortName, pipelineName))
            # TODO - write "getPath()
            cmd.append("--platform=%s" % self.getPath(wfConfig.platform))
            cmd.append("--localrepos=%s" % self.dirs.get("work"))
            workflowIndex = 1
            for wfConfig in workflowConfigs:
                if wfConfig.shortName == wfShortName:
                    #cmd.append("--activoffset=%s" % workflowIndex)
                    cmd.append("--activoffset=%s" % globalPipelineOffset)
                    break
                workflowIndex = workflowIndex + 1
            launchCmd = ' '.join(cmd)

            # extract the pipeline config and all the files it includes, and add it to the command
            filelist = provSetup.extractSinglePipelineFileNames(pipelineConfig, self.repository, self.logger)
            fileargs = ' '.join(filelist)
            launcher.write("%s %s\n" % (launchCmd, fileargs))

        
        launcher.write("%s %s %s -L %s --logdir %s --workerid %s >%s/launch.log 2>&1\n" % (execCmd, filename, self.runid, self.wfVerbosity, logDir, pipelineName, logDir))
        launcher.write("./workerdone.py %s %s %s\n" % (self.eventBrokerHost, self.runid, pipelineName))
        launcher.close()
        # make it executable
        os.chmod(name, stat.S_IRWXU)

        launchCmd = ["ssh", self.masterNode, name]

        # print "cmd to execute is: ",launchCmd
        return launchCmd

    ##
    # @brief create the platform.dir directories
    #
    def createDirs(self, platformConfig, pipelineConfig):
        self.logger.log(Log.DEBUG, "GenericPipelineWorkflowConfigurator:createDirs")

        dirConfig = platformConfig.dir
        dirName = pipelineConfig.shortName
        self.directories = Directories(dirConfig, dirName, self.runid)
        self.dirs = self.directories.getDirs()
        self.defaultRootDir = self.directories.getDefaultRootDir()

        for name in self.dirs.names():
            localDirName = self.dirs.get(name)
            if not os.path.exists(localDirName):
                os.makedirs(localDirName)

    ##
    # @brief set up this workflow's database
    #
    def setupDatabase(self):
        self.logger.log(Log.DEBUG, "GenericPipelineWorkflowConfigurator:setupDatabase")

    ##
    # @brief perform a node host name expansion
    #
    def expandNodeHost(self, nodeentry):
        """Add a default network domain to a node list entry if necessary """

        if nodeentry.find(".") < 0:
            node = nodeentry
            colon = nodeentry.find(":")
            if colon == 0:
                raise RuntimeError("bad nodelist format: " + nodeentry)
            elif colon > 0:
                node = nodeentry[0:colon]
                if len(node) < 3:
                    #logger.log(Log.WARN, "Suspiciously short node name: " + node)
                    self.logger.log(Log.DEBUG, "Suspiciously short node name: " + node)
                self.logger.log(Log.DEBUG, "-> nodeentry  =" + nodeentry)
                self.logger.log(Log.DEBUG, "-> node  =" + node)

                if self.defaultDomain is not None:
                    node += "."+self.defaultDomain
                nodeentry = "%s:%s" % (node, nodeentry[colon+1:])
            else:
                if self.defaultDomain is not None:
                    nodeentry = "%s%s:1" % (node, self.defaultDomain)
                else:
                    nodeentry = "%s:1" % node
        return nodeentry
