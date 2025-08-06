name: "crawler"

includes:
  - resource: true
    file: "/crawler-conf.yaml"
    override: false

config:
  # Required configs that must be provided
  topology.workers: 1
  topology.message.timeout.secs: 300
  topology.max.spout.pending: 100
  topology.debug: false
  topology.name: "stormcrawler-enterprise"
  
  # Logging configuration
  topology.worker.childopts: "-Dlog4j.configurationFile=log4j2.properties -Dlog4j2.formatMsgNoLookups=true"
  
  # Elasticsearch configuration
  es.indexer.addresses: ["http://elasticsearch:9200"]
  es.indexer.index.name: "content"
  es.indexer.doc.type: "_doc"
  es.indexer.create: true
  es.indexer.settings:
    cluster.name: "stormcrawler"
    client.transport.sniff: false

  # Index options  
  es.indexer.flushInterval: "5s"
  es.indexer.bulkActions: 50
  es.indexer.bulkSize: "5mb"
  es.indexer.concurrentRequests: 1

  # SQL status storage configuration
  sql.connection.string: "jdbc:oracle:thin:@//oracle-test:1521/XE"
  sql.user: "c##mojtaba"
  sql.password: "bjnSY55l0g1IrzWY71Jg"
  sql.status.table: "crawl_queue"
  sql.max.retries: 3
  sql.retry.interval.ms: 2000
  sql.show.sql: true

  # Fetcher configuration
  fetcher.server.delay: 1.0
  fetcher.threads.number: 10
  fetcher.max.urls.in.queues: 100

  # HTTP protocol
  http.agent.name: "StormCrawler Enterprise"
  http.agent.version: "1.0"
  http.agent.description: "Enterprise web crawler"

spouts:
  - id: "spout"
    className: "com.digitalpebble.SimpleOracleSpout"
    parallelism: 1

bolts:
  - id: "partitioner"
    className: "com.digitalpebble.stormcrawler.bolt.URLPartitionerBolt"
    parallelism: 1

  - id: "fetcher" 
    className: "com.digitalpebble.stormcrawler.bolt.FetcherBolt"
    parallelism: 2
    
  - id: "sitemap"
    className: "com.digitalpebble.stormcrawler.bolt.SiteMapParserBolt"
    parallelism: 1
    
  - id: "parse"
    className: "com.digitalpebble.stormcrawler.bolt.JSoupParserBolt" 
    parallelism: 2

  - id: "index"
    className: "com.digitalpebble.stormcrawler.elasticsearch.bolt.IndexerBolt"
    parallelism: 1

  - id: "status"
    className: "com.digitalpebble.SQLStatusUpdaterBolt"
    parallelism: 1

  - id: "debug"
    className: "com.digitalpebble.DebugBolt"
    parallelism: 1

streams:
  # Main processing flow
  - from: "spout"
    to: "partitioner"
    grouping:
      type: SHUFFLE

  - from: "partitioner"
    to: "fetcher"
    grouping:
      type: FIELDS
      args: ["key"]

  - from: "fetcher"
    to: "sitemap"
    grouping:
      type: LOCAL_OR_SHUFFLE

  - from: "sitemap" 
    to: "parse"
    grouping:
      type: LOCAL_OR_SHUFFLE

  - from: "fetcher"
    to: "parse"
    grouping:
      type: LOCAL_OR_SHUFFLE

  - from: "parse"
    to: "index"
    grouping:
      type: LOCAL_OR_SHUFFLE

  # Status update streams - collect all status updates
  - from: "fetcher"
    to: "status"
    grouping:
      type: FIELDS
      args: ["url"]
      streamId: "status"

  - from: "sitemap"
    to: "status" 
    grouping:
      type: FIELDS
      args: ["url"]
      streamId: "status"

  - from: "parse"
    to: "status"
    grouping:
      type: FIELDS
      args: ["url"] 
      streamId: "status"

  - from: "index"
    to: "status"
    grouping:
      type: FIELDS
      args: ["url"]
      streamId: "status"

  # Debug stream
  - from: "spout"
    to: "debug"
    grouping:
      type: SHUFFLE