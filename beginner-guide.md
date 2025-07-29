## StormCrawler Enterprise Setup Guide

A concise guide for setting up a StormCrawler enterprise environment using Docker, Maven, and Java. Commands and files are shown in full with minimal comments.

---

### 0. (Optional) Clean Previous Docker State

```bash
# Stop containers, remove images, volumes, networks, and prune
docker-compose down
docker kill $(docker ps -q) 2>/dev/null || true
docker rm $(docker ps -aq) 2>/dev/null || true
docker rmi -f $(docker images -aq) 2>/dev/null || true
docker volume rm $(docker volume ls -q) 2>/dev/null || true
docker network rm $(docker network ls -q) 2>/dev/null || true
docker system prune --all --volumes --force
```

---

### 1. Prepare the Project Directory

```bash
mkdir -p ~/stormcrawler-enterprise
cd ~/stormcrawler-enterprise
mkdir frontier
chmod 777 frontier
```

---

### 2. Dockerfile

```dockerfile
FROM storm:2.7.0
USER root
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y maven openjdk-11-jdk \
 && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
USER storm
WORKDIR /home/storm
```

---

### 3. docker-compose.yml

```yaml
version: "3.8"
services:
  zookeeper:
    image: zookeeper:3.9.2
    restart: always
    volumes: [zk-logs:/logs, zk-data:/data, zk-datalog:/datalog]

  nimbus:
    image: storm:2.7.0
    command: storm nimbus
    depends_on: [zookeeper]
    restart: always
    volumes: [storm-nimbus-logs:/logs]

  supervisor:
    image: storm:2.7.0
    command: storm supervisor
    depends_on: [nimbus, zookeeper]
    restart: always
    volumes: [storm-supervisor-logs:/logs]
    deploy: {replicas: 2}

  ui:
    image: storm:2.7.0
    command: storm ui
    depends_on: [nimbus]
    ports: ["8080:8080"]
    restart: always
    volumes: [storm-ui-logs:/logs]

  frontier:
    image: crawlercommons/url-frontier
    command: rocksdb.path=/crawldir/rocksdb
    ports: ["7071:7071"]
    volumes: [./frontier:/crawldir]

  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.6.0
    environment:
      - discovery.type=single-node
      - "ES_JAVA_OPTS=-Xms1g -Xmx1g"
    ports: ["9200:9200"]
    volumes: [es-data:/usr/share/elasticsearch/data]

  runner:
    build: .
    depends_on: [nimbus, frontier]
    volumes: ["./crawldata:/home/storm/crawldata"]
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

---

### 4. StormCrawler Maven Project

```bash
mvn archetype:generate \
  -DarchetypeGroupId=com.digitalpebble.stormcrawler \
  -DarchetypeArtifactId=storm-crawler-archetype \
  -DarchetypeVersion=2.9 \
  -DgroupId=com.mycompany \
  -DartifactId=crawldata \
  -Dversion=1.0 \
  -DinteractiveMode=false
chmod -R a+rw crawldata
```

---

### 5. Configuration Files

#### 5.1 Top‐Level `crawler-conf.yaml`

```yaml
# crawler-conf.yaml

topology.workers: 4
spout.fetcher.class: com.digitalpebble.stormcrawler.spout.FrontierSpout
spout.fetcher.parallelism: 2
bolt.fetcher.class: com.digitalpebble.stormcrawler.fetcher.FetcherBolt
bolt.fetcher.parallelism: 4
bolt.parser.class: com.digitalpebble.stormcrawler.parse.ParseBolt
bolt.parser.parallelism: 4
bolt.status.class: com.digitalpebble.stormcrawler.bolt.StatusUpdaterBolt
bolt.status.parallelism: 2
bolt.indexer.class: com.digitalpebble.stormcrawler.elasticsearch.ElasticSearchIndexerBolt
bolt.indexer.parallelism: 4
url.frontier.grpc.host: "frontier"
url.frontier.grpc.port: 7071
```

#### 5.2 Project‐Level `crawler-conf.yaml`

```yaml
# crawldata/src/main/resources/crawler-conf.yaml

config:
  topology.workers: 4
  topology.message.timeout.secs: 300
  topology.max.spout.pending: 100
  topology.debug: false

  spout.fetcher.class: com.digitalpebble.stormcrawler.spout.FrontierSpout
  spout.fetcher.parallelism: 2

  bolt.fetcher.class: com.digitalpebble.stormcrawler.fetcher.FetcherBolt
  bolt.fetcher.parallelism: 4

  bolt.parser.class: com.digitalpebble.stormcrawler.parse.ParseBolt
  bolt.parser.parallelism: 4

  bolt.status.class: com.digitalpebble.stormcrawler.bolt.StatusUpdaterBolt
  bolt.status.parallelism: 2

  bolt.indexer.class: com.digitalpebble.stormcrawler.elasticsearch.ElasticSearchIndexerBolt
  bolt.indexer.parallelism: 4

  url.frontier.grpc.host: "frontier"
  url.frontier.grpc.port: 7071

  fetcher.threads.number: 50
  topology.worker.childopts: "-Xmx2g -Djava.net.preferIPv4Stack=true"

  topology.kryo.register:
    - com.digitalpebble.stormcrawler.Metadata
    - com.digitalpebble.stormcrawler.persistence.Status

  metadata.persist:
    - _redirTo
    - error.cause
    - error.source
    - isSitemap
    - isFeed

  http.agent.name: "Anonymous Coward"
  http.agent.version: "1.0"
  http.agent.description: "built with StormCrawler Archetype 2.9"
  http.agent.url: "http://someorganization.com/"
  http.agent.email: "someone@someorganization.com"

  http.protocol.implementation: "com.digitalpebble.stormcrawler.protocol.okhttp.HttpProtocol"
  https.protocol.implementation: "com.digitalpebble.stormcrawler.protocol.okhttp.HttpProtocol"

  http.content.limit: 65536

  parsefilters.config.file: "parsefilters.json"
  urlfilters.config.file:   "urlfilters.json"
  jsoup.filters.config.file: "jsoupfilters.json"

  fetchInterval.default:       1440
  fetchInterval.fetch.error:   120
  fetchInterval.error:        -1

  textextractor.no.text: false
  textextractor.include.pattern:
    - DIV[id="maincontent"]
    - DIV[itemprop="articleBody"]
    - ARTICLE
  textextractor.exclude.tags:
    - STYLE
    - SCRIPT
  jsoup.treat.non.html.as.error: false

  parser.mimetype.whitelist:
    - application/.+word.*
    - application/.+excel.*
    - application/.+powerpoint.*
    - application/.*pdf.*
  parse.tika.config.file: "tika-config.xml"

  indexer.url.fieldname:   "url"
  indexer.text.fieldname:  "content"
  indexer.canonical.name:  "canonical"
  indexer.md.mapping:
    - parse.title=title
    - parse.keywords=keywords
    - parse.description=description
    - domain
    - format

  topology.metrics.consumer.register:
    - class: "org.apache.storm.metric.LoggingMetricsConsumer"
      parallelism.hint: 1
```

#### 5.3 Top‐Level `indexer-es.yaml`

```yaml
# indexer-es.yaml

es.status.mapping: status
es.index.mapping: crawler
es.indexing.document.id: metadata.url
es.indexing.document.parent: metadata.domain
es.indexing.bulk.size: 100
es.indexing.bulk.interval.ms: 2000

es.hosts:
  - host: "elasticsearch"
    port: 9200
```

#### 5.4 Project‐Level `indexer-es.yaml`

```yaml
# crawldata/src/main/resources/indexer-es.yaml

es.status.mapping: status
es.index.mapping: crawler
es.indexing.document.id: metadata.url
es.indexing.document.parent: metadata.domain
es.indexing.bulk.size: 100
es.indexing.bulk.interval.ms: 2000

es.hosts:
  - host: "elasticsearch"
    port: 9200

# Optional TLS/auth
# es.scheme: "https"
# es.username: "elastic"
# es.password: "changeme"
# es.truststore.path: "/path/to/truststore.jks"
# es.truststore.password: "secret"
```

---

### 6. Java Topology Class

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

public class StormCrawlerTopology extends ConfigurableTopology {

    @Override
    protected int run(String[] args) {
        if (args.length < 3) return -1;
        String topologyName = args[0];
        TopologyBuilder builder = new TopologyBuilder();
        int spoutPar = ConfUtils.getInt(conf, "spout.fetcher.parallelism", 1);
        int fetcherPar = ConfUtils.getInt(conf, "bolt.fetcher.parallelism", 1);
        int parserPar = ConfUtils.getInt(conf, "bolt.parser.parallelism", 1);
        int statusPar = ConfUtils.getInt(conf, "bolt.status.parallelism", 1);
        int indexerPar = ConfUtils.getInt(conf, "bolt.indexer.parallelism", 1);
        builder.setSpout("spout", new Spout(), spoutPar);
        builder.setBolt("fetch", new FetcherBolt(), fetcherPar).shuffleGrouping("spout");
        builder.setBolt("parse", new JSoupParserBolt(), parserPar).shuffleGrouping("fetch");
        builder.setBolt("status", new StatusUpdaterBolt(), statusPar).shuffleGrouping("parse");
        builder.setBolt("index", new IndexerBolt(), indexerPar).shuffleGrouping("status");
        return submit(topologyName, conf, builder);
    }

    public static void main(String[] args) throws Exception {
        ConfigurableTopology.start(new StormCrawlerTopology(), args);
    }
}
```

---

### 7. pom.xml Assembly Plugin

```xml
<plugin>
  <groupId>org.apache.maven.plugins</groupId>
  <artifactId>maven-assembly-plugin</artifactId>
  <version>2.4</version>
  <configuration>
    <descriptorRefs><descriptorRef>jar-with-dependencies</descriptorRef></descriptorRefs>
    <archive><manifest><mainClass>org.apache.storm.flux.Flux</mainClass></manifest></archive>
  </configuration>
  <executions>
    <execution><id>make-assembly</id><phase>package</phase><goals><goal>single</goal></goals></execution>
  </executions>
</plugin>
```

---

### 8. Build the Fat JAR

```bash
cd crawldata
mvn clean package
cd ..
ls crawldata/target/crawldata-1.0-jar-with-dependencies.jar
```

---

### 9. Start All Services

```bash
docker-compose up -d
docker ps | grep -E 'frontier|nimbus|supervisor|ui|elasticsearch'
```

---

### 10. Seed the URL Frontier

```bash
cat > seeds.jsonl << 'EOF'
{ "discovered": { "info": { "url":"https://www.yjc.ir/en/iran","key":"www.yjc.ir","metadata":{},"crawlID":"" } } }
{ "discovered": { "info": { "url":"https://www.yjc.ir/en/news/57286/fm-us-must-stay-away-from-ambiguities-to-reach-agreement","key":"www.yjc.ir","metadata":{},"crawlID":"" } } }
EOF

grpcurl -plaintext -import-path . -proto urlfrontier.proto -d @ localhost:7071 urlfrontier.URLFrontier/PutURLs < seeds.jsonl
```

---

### 11. Submit the Topology

```bash
docker-compose run --rm runner bash
cd crawldata
storm jar target/crawldata-1.0-jar-with-dependencies.jar \
  com.mycompany.StormCrawlerTopology \
  stormcrawler-topology \
  crawler-conf.yaml \
  indexer-es.yaml \
  --local
exit
```

---

You're all set. Happy crawling! 🚀
