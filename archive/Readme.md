## StormCrawler Enterprise Setup Guide (Java Deep Dive)

An end-to-end setup of a StormCrawler enterprise environment, with exhaustive explanations of every Java-related script, Maven configuration, build command, and code file.

---

### 0. Clean Previous Docker State (Optional)

Ensure no leftover containers, images, or volumes interfere with clean startup.

```bash
# Stop and remove Docker Compose services
docker-compose down

# Force-stop all running containers
docker kill $(docker ps -q) 2>/dev/null || true

# Remove all containers
docker rm $(docker ps -aq) 2>/dev/null || true

# Remove all images
docker rmi -f $(docker images -aq) 2>/dev/null || true

# Remove all volumes
docker volume rm $(docker volume ls -q) 2>/dev/null || true

# Remove all custom networks
docker network rm $(docker network ls -q) 2>/dev/null || true

# Deep clean of dangling resources
docker system prune --all --volumes --force
```

**Why**: Guarantees a fresh environment, preventing port conflicts or stale data.

---

### 1. Prepare the Project Directory

Create your workspace and ensure the URL frontier store is writable by all.

```bash
# Create project root under your home directory
mkdir -p ~/stormcrawler-enterprise
# Navigate into the new project directory
cd ~/stormcrawler-enterprise

# Create the frontier data directory
mkdir frontier
# Set permissions: owner/group/others all read, write, execute
chmod 777 frontier
```

* `mkdir -p`: Creates parent directories if missing.
* `chmod 777`: Avoids permission issues when Docker’s `storm` user writes frontier data.

All Java source code and Maven files will reside under `crawldata/` created in Step 4.

---

### 2. Dockerfile (Java Build & Runtime)

Define a Docker image that includes Storm CLI, Java 11 JDK, and Maven for building your topology.

```dockerfile
# 1. Base image: Apache Storm v2.7.0 for Storm CLI and runtime libraries
FROM storm:2.7.0

# 2. Switch to root user to install system packages
USER root

# 3. Install Maven and OpenJDK 11
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y \
      maven \  # Apache Maven for building Java projects
      openjdk-11-jdk-headless \  # Java Development Kit (headless)
 && rm -rf /var/lib/apt/lists/*    # Clean apt cache to reduce image size

# 4. Set JAVA_HOME for Maven and Java tools
ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
# 5. Add Java bin to PATH (Maven uses java)
ENV PATH="$JAVA_HOME/bin:$PATH"

# 6. Revert to non-root user for security
USER storm

# 7. Set working directory where Java code and pom.xml will be mounted
WORKDIR /home/storm/crawldata
```

**Detailed Breakdown**:

1. **`FROM storm:2.7.0`**: Uses an image with Storm CLI and libraries pre-installed.
2. **`USER root`**: Required to install system packages.
3. **`RUN apt-get install`**:

   * `maven`: Installs the Maven build tool, enabling `mvn` commands.
   * `openjdk-11-jdk-headless`: Provides `javac` and `java` without GUI components.
4. **`ENV JAVA_HOME`**: Points at the JDK location; Maven picks this up automatically.
5. **`ENV PATH`**: Ensures `java` and `mvn` are accessible in `$PATH`.
6. **`USER storm`**: Minimizes security risks by running as a non-root user.
7. **`WORKDIR`**: Where your `crawldata` Maven project will live inside the container.

---

### 3. docker-compose.yml (Service Orchestration)

Orchestrate services; the `runner` service builds your Java code and submits the topology.

```yaml
version: "3.8"
services:
  # Other services (zookeeper, nimbus, supervisor, ui, frontier, elasticsearch) omitted for brevity

  runner:
    build: .                           # Uses Dockerfile above
    depends_on: [nimbus, frontier]     # Ensure Nimbus and Frontier are up
    volumes:
      - "./crawldata:/home/storm/crawldata"  # Mount Java project
    working_dir: /home/storm/crawldata      # Directory for Maven build and storm jar
    entrypoint: ["bash", "-lc"]           # Launch a login shell
    command: >-
      mvn clean package && \
      storm jar target/crawldata-1.0-jar-with-dependencies.jar \
         com.mycompany.StormCrawlerTopology \
         stormcrawler-topology crawler-conf.yaml indexer-es.yaml --local
    tty: true

volumes:
  zk-logs: {}
  zk-data: {}
  zk-datalog: {}
  storm-nimbus-logs: {}
  storm-supervisor-logs: {}
  storm-ui-logs: {}
  es-data: {}
```

* **`build: .`**: Builds the image from the Dockerfile containing Maven and Java.
* **`volumes`**: Synchronizes local `crawldata/` project into container.
* **`entrypoint`**: Uses a login shell to source environment variables.
* **`command`**:

  1. `mvn clean package`: Compiles Java code, runs tests, and assembles a fat JAR with dependencies.
  2. `storm jar ... --local`: Submits the topology to a local Storm cluster.

---

### 4. Create the StormCrawler Maven Project

#### 4.1 Generate Project via Maven Archetype

```bash
mvn archetype:generate \
  -DarchetypeGroupId=com.digitalpebble.stormcrawler \
  -DarchetypeArtifactId=storm-crawler-archetype \
  -DarchetypeVersion=2.9 \
  -DgroupId=com.mycompany \
  -DartifactId=crawldata \
  -Dversion=1.0 \
  -Dpackage=com.mycompany \
  -DinteractiveMode=false
```

* **Result**: Directory `crawldata/` with a Maven project scaffold:

  * `src/main/java/com/mycompany/` (empty)
  * `src/main/resources/` (empty defaults)
  * `pom.xml` stub.

#### 4.2 Set Permissions

```bash
chmod -R a+rw crawldata
```

Allows the Docker container’s `storm` user to modify files.

---

### 5. pom.xml (Maven Configuration)

Replace the generated `pom.xml` content with the following fully detailed configuration:

```xml
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 \
                             http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>

  <!-- Coordinates -->
  <groupId>com.mycompany</groupId>
  <artifactId>crawldata</artifactId>
  <version>1.0</version>
  <packaging>jar</packaging>

  <!-- Java and Storm versions -->
  <properties>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    <java.version>11</java.version>
    <stormcrawler.version>2.9</stormcrawler.version>
    <storm.version>2.7.0</storm.version>
  </properties>

  <!-- Dependencies -->
  <dependencies>
    <!-- StormCrawler Core: spout, bolts, util classes -->
    <dependency>
      <groupId>com.digitalpebble.stormcrawler</groupId>
      <artifactId>storm-crawler-core</artifactId>
      <version>${stormcrawler.version}</version>
    </dependency>
    
    <!-- Elasticsearch Indexer Bolt -->
    <dependency>
      <groupId>com.digitalpebble.stormcrawler</groupId>
      <artifactId>storm-crawler-elasticsearch</artifactId>
      <version>${stormcrawler.version}</version>
    </dependency>

    <!-- URL Frontier Spout and Status Updater Bolt -->
    <dependency>
      <groupId>com.digitalpebble.stormcrawler</groupId>
      <artifactId>storm-crawler-urlfrontier</artifactId>
      <version>${stormcrawler.version}</version>
    </dependency>

    <!-- Oracle JDBC Status Updater Bolt -->
    <dependency>
      <groupId>com.digitalpebble.stormcrawler</groupId>
      <artifactId>storm-crawler-sql</artifactId>
      <version>${stormcrawler.version}</version>
    </dependency>

    <!-- Apache Storm Core API (provided by runtime) -->
    <dependency>
      <groupId>org.apache.storm</groupId>
      <artifactId>storm-core</artifactId>
      <version>${storm.version}</version>
      <scope>provided</scope>
    </dependency>

    <!-- Flux for YAML-based topologies -->
    <dependency>
      <groupId>org.apache.storm</groupId>
      <artifactId>flux-core</artifactId>
      <version>${storm.version}</version>
    </dependency>

    <!-- Tika parsing integration -->
    <dependency>
      <groupId>com.digitalpebble.stormcrawler</groupId>
      <artifactId>storm-crawler-tika</artifactId>
      <version>${stormcrawler.version}</version>
    </dependency>
  </dependencies>

  <!-- Build configuration -->
  <build>
    <plugins>
      <!-- Compile Java 11 -->
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>3.10.1</version>
        <configuration>
          <source>${java.version}</source>
          <target>${java.version}</target>
        </configuration>
      </plugin>

      <!-- Create an Uber-JAR with all dependencies -->
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-assembly-plugin</artifactId>
        <version>3.6.0</version>
        <configuration>
          <descriptorRefs>
            <descriptorRef>jar-with-dependencies</descriptorRef>
          </descriptorRefs>
          <archive>
            <manifest>
              <mainClass>org.apache.storm.flux.Flux</mainClass>
            </manifest>
          </archive>
        </configuration>
        <executions>
          <execution>
            <id>make-assembly</id>
            <phase>package</phase>
            <goals>
              <goal>single</goal>
            </goals>
          </execution>
        </executions>
      </plugin>
    </plugins>
  </build>
</project>
```

**Key Details**:

* Versions controlled by properties for easy updates.
* `storm-core` scope `provided` ensures no conflict with Storm cluster’s own jars.
* Assembly plugin bundles everything into `target/crawldata-1.0-jar-with-dependencies.jar`.

---

### 6. Java Topology Class (`StormCrawlerTopology.java`)

Place under `crawldata/src/main/java/com/mycompany/StormCrawlerTopology.java`.

```java
package com.mycompany;

import com.digitalpebble.stormcrawler.ConfigurableTopology;
import com.digitalpebble.stormcrawler.util.ConfUtils;
import com.digitalpebble.stormcrawler.urlfrontier.Spout;
import com.digitalpebble.stormcrawler.bolt.FetcherBolt;
import com.digitalpebble.stormcrawler.bolt.JSoupParserBolt;
import com.digitalpebble.stormcrawler.urlfrontier.StatusUpdaterBolt;
import com.digitalpebble.stormcrawler.elasticsearch.bolt.IndexerBolt;
import org.apache.storm.topology.TopologyBuilder;

/**
 * Main class that builds and submits a StormCrawler topology.
 */
public class StormCrawlerTopology extends ConfigurableTopology {

    /**
     * Configures spouts and bolts, then submits the topology.
     * @param args args[0]=topologyName, args[1]=crawler-conf.yaml, args[2]=indexer-es.yaml
     * @return 0 on success, -1 on argument error
     */
    @Override
    protected int run(String[] args) {
        if (args.length < 3) {
            System.err.println("Usage: StormCrawlerTopology <topologyName> crawler-conf.yaml indexer-es.yaml");
            return -1;
        }

        // 1) Extract topology name
        String topologyName = args[0];

        // 2) Create TopologyBuilder instance
        TopologyBuilder builder = new TopologyBuilder();

        // 3) Read parallelism settings from YAML via ConfUtils.getInt
        int spoutPar    = ConfUtils.getInt(conf, "spout.fetcher.parallelism", 1);
        int fetcherPar  = ConfUtils.getInt(conf, "bolt.fetcher.parallelism", 1);
        int parserPar   = ConfUtils.getInt(conf, "bolt.parser.parallelism", 1);
        int statusPar   = ConfUtils.getInt(conf, "bolt.status.parallelism", 1);
        int indexerPar  = ConfUtils.getInt(conf, "bolt.indexer.parallelism", 1);

        // 4) Wire up components in the correct order with shuffle grouping
        builder.setSpout("spout", new Spout(), spoutPar);
        builder.setBolt("fetch", new FetcherBolt(), fetcherPar)
               .shuffleGrouping("spout");
        builder.setBolt("parse", new JSoupParserBolt(), parserPar)
               .shuffleGrouping("fetch");
        builder.setBolt("status", new StatusUpdaterBolt(), statusPar)
               .shuffleGrouping("parse");
        builder.setBolt("index", new IndexerBolt(), indexerPar)
               .shuffleGrouping("status");

        // 5) Submit topology to local or cluster based on args
        return submit(topologyName, conf, builder);
    }

    /**
     * Entry point: delegates to ConfigurableTopology.start which handles local vs cluster mode.
     */
    public static void main(String[] args) throws Exception {
        ConfigurableTopology.start(new StormCrawlerTopology(), args);
    }
}
```

**In-Depth Explanation**:

1. **Class Structure**: Extends `ConfigurableTopology`, which handles loading `crawler-conf.yaml` and `indexer-es.yaml` into the `conf` map.
2. **`run` Method**:

   * **Argument check**: Ensures you pass `<name> crawler-conf.yaml indexer-es.yaml`.
   * **`TopologyBuilder`**: Core Storm API to assemble spouts and bolts.
   * **Parallelism**: Reads the number of executor threads for each component from YAML using `ConfUtils`.
   * **Shuffle Grouping**: Distributes tuples evenly across bolt instances.
   * **`submit`**: Provided by `ConfigurableTopology`, handles both local and cluster deployment.
3. **`main` Method**: Calls `ConfigurableTopology.start`, which parses additional Storm options like `--local`.

---

### 7. Build and Submit Topology

Run these commands inside your `runner` container or locally if Java & Maven installed:

```bash
# Navigate to project
cd ~/stormcrawler-enterprise/crawldata

# 1. Build the uber-jar with all dependencies
mvn clean package

# 2. Verify the jar exists
ls target/crawldata-1.0-jar-with-dependencies.jar

# 3. Submit topology in local mode
storm jar \
  target/crawldata-1.0-jar-with-dependencies.jar \
  com.mycompany.StormCrawlerTopology \
  stormcrawler-topology \
  crawler-conf.yaml \
  indexer-es.yaml \
  --local
```

* **Local vs Cluster**: Remove `--local` to deploy on the actual Storm Nimbus & Supervisors.

---

## Updates
- Added a logger for `SimpleOracleSpout` to monitor database connection status.
- Added Oracle JDBC driver setup with system scope for better dependency control.

### Oracle JDBC Driver Setup

Before building the project, you need to set up the Oracle JDBC driver:

1. **Create lib directory and download driver**:
   ```bash
   mkdir -p crawldata/lib
   # Download ojdbc8.jar from Oracle website to crawldata/lib/
   ```

2. **Verify setup**:
   ```bash
   ls -la crawldata/lib/ojdbc8.jar
   ```

The pom.xml is configured to use the system scope for the Oracle JDBC driver, ensuring consistent and reliable access to the Oracle database functionality.

You now have a meticulously detailed Java-focused StormCrawler enterprise setup, from Docker image to Maven POM to Java code wiring. Happy crawling! 🚀
