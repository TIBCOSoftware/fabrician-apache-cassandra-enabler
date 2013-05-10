[fabrician.org](http://fabrician.org/) - Apache Cassandra Enabler Guide
==========================================================================

Introduction
--------------------------------------
A Silver Fabric Enabler allows an external application or application platform, such as a J2EE 
application server to run in a TIBCO Silver Fabric software environment.  The Silver Fabric Apache 
Cassandra Enabler supports configuration, runtime management, JMX health and performance 
monitoring of an Apache Cassandra cluster.

Installation
--------------------------------------
The Apache Cassandra Enabler consists of an Enabler Runtime Grid Library and a Distribution 
Grid Library. The Enabler Runtime contains information specific to a Silver Fabric version that 
is used to integrate the Enabler, and the Distribution contains the scripts and libraries that 
makeup Cassandra. Installation of the Apache Cassandra Enabler involves copying these Grid 
Libraries to the SF_HOME/webapps/livecluster/deploy/resources/gridlib directory on the Silver Fabric Broker. 

Testing the Deployment
--------------------------------------
* Start a Cassandra Component on Silver Fabric.  See the TIBCO Silver Fabric documentation for more information.
* Note: If you are testing the installation on only one engine you will have to set the MIN_SEED_NODES to 1.
* You will also have to specify a value for SEED_CONFIG_DIR that will be accessible from all nodes.
* Connect to the Engine machine. Using a cmd (Windows) or a shell (Linux).
* Change into the directory ENGINE_WORK_DIR/cassandra/bin and run

```bash
./nodetool -u monitorRole -pw changeit -p 9000 info
```

Note that the JMX_PORT is set by default to 9000.  This is set during configuration as can be seen
with a snippet from configure.xml
```xml
    <configFiles baseDir="${CASSANDRA_CONF}" include="cassandra-env.sh">
        <regex pattern='-Dcom\.sun\.management\.jmxremote\.port=\$JMX_PORT' replacement='-Dcom.sun.management.jmxremote.port=${RMI_REGISTRY_PORT}' />
        <regex pattern='-Dcom\.sun\.management\.jmxremote\.ssl=[a-zA-Z]+' replacement='-Dcom.sun.management.jmxremote.ssl=${JMX_SSL_ENABLED}' />
        <regex pattern='-Dcom\.sun\.management\.jmxremote\.authenticate=[a-zA-Z]+' replacement='-Dcom.sun.management.jmxremote.authenticate=true' />
    </configFiles>
```
These Runtime Context variables can be overridden when defining you Cassandra component.


Runtime Grid Library
--------------------------------------
The Enabler Runtime Grid Library is created by building the maven project:
```bash
mvn package
```
The version of the distribution can be optionally overridden:
```bash
mvn package -Ddistribution.version=1.2.4
```

Distribution Grid Library
--------------------------------------
The Distribution Grid Library is created by performing the following steps:
* Download the Apache Cassandra binary distribution apache-cassandra-1.2.4-bin.tar.gz from http://cassandra.apache.org/download
* Build the maven project with the location of the archive.

```bash
mvn package -Ddistribution.location=/home/you/Downloads/apache-cassandra-1.2.4-bin.tar.gz -Ddistribution.version=1.2.4 
```

Architecture Summary
--------------------------------------
All nodes listen on the same configurable port used for inter-node communication within a cluster so running multiple nodes 
per cluster will result in port collision. 

In the case of non-persistent data, the entire clustered is destroyed on cluster shutdown and all data is lost. This mode 
is suitable for testing purposes only.

In case of persistent data, cluster nodes need to be run on a fixed pool of hosts, one node per host, and data must be stored on 
same local directory path on each node, e.g. /opt/cassandra/data. This implies the cluster must be run on the same pool of hosts
in case of persistent data. If the cluster size is increased, no manual intervention is needed. However, if cluster size is 
decreased permanently, it is recommended, but not required, that you manually remove the dropped node from the cluster using 
nodetool command from any of the running nodes. 

Feature Summary
--------------------------------------
<table>
<tr>
<th>Feature</th>
<th>Summary</th>
</tr>

<tr>
<td>Cluster support</td>
<td>yes</td>
</tr>

<tr>
<td>Dynamic clustering support</td>
<td>Available with non-persistent data in scale up and scale down mode.  Only available in scale up mode in case of persistent data.</td>
</tr>

<tr>
<td>Tracked statistics</td>
<td>Read Latency Mean, Write Latency Mean, Storage Load, Commit Log Active Count, Commit Log Pending Tasks, 
Commit Log Completed Tasks, Compaction Bytes in Progress and Compaction Bytes Completed. Other statistics 
can be enabled as required.
</td>
</tr>

<tr>
<td>Persistent software install support</td>
<td>No</td>
</tr>

<tr>
<td>Persistent data support</td>
<td>Yes</td>
</tr>

<tr>
<td>Node cleanup</td>
<td>Cassandra recommends running cleanup on nodes at various points in time. This task is not automated in this 
version of the enabler.</td>
</tr>
</table>

Component Configuration
--------------------------------------
To configure a Silver Fabric Component based on this enabler, use Default Component Type. Following Runtime 
Variables must be configured or reviewed in a typical Component configuration:

<table>
<tr>
<th>Runtime Context Variable</th>
<th>Description</th>
<th>Default Value</th>
<th>Exported to Dependent Components</th>
</tr>

<tr>
<td>SEED_CONFIG_DIR</td>
<td>Shared NFS directory under which the component creates a unique directory used for cluster seed nodes discovery</td>
<td></td>
<td>No</td>
</tr>

<tr>
<td>JMX_USERNAME</td>
<td>JMX user name used to remotely connect with Cassandra Node</td>
<td>monitorRole</td>
<td>No</td>
</tr>

<tr>
<td>JMX_PASSWORD</td>
<td>JMX password used to remotely connect with Cassandra Node</td>
<td>changeit</td>
<td>No</td>
</tr>

<tr>
<td>MIN_SEED_NODES</td>
<td>Minimum of seed nodes in the cluster</td>
<td>2</td>
<td>No</td>
</tr>

</table>

Stack Configuration
--------------------------------------
To configure a Silver Fabric Stack to define a Cassandra cluster, set the minimum number of components in the 
stack to be greater than or equal to the setting for the MIN_SEED_NODES. You only need to include one component 
based on this enabler in the stack to define a Cassandra cluster.
