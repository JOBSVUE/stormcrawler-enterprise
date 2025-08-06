name: "crawler"

config:
  # Required configs that must be provided
  topology.workers: 1
  topology.message.timeout.secs: 300
  topology.max.spout.pending: 100
  topology.debug: false
  
  # Elasticsearch configuration
  es.indexer.addresses: ["http://elasticsearch:9200"]
  es.indexer.index.name: "content"
  es.indexer.create: true
  es.indexer.settings:
    cluster.name: "stormcrawler"
    client.transport.sniff: false
    request.headers.Accept: "application/json"
    request.headers.Content-Type: "application/json"

  # Index options  
  es.indexer.flushInterval: "5s"
  es.indexer.bulkActions: 50
  es.indexer.bulkSize: "5mb"
  es.indexer.concurrentRequests: 1

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
    parallelism: 1
    
  - id: "sitemap"
    className: "com.digitalpebble.stormcrawler.bolt.SiteMapParserBolt"
    parallelism: 1
    
  - id: "parse"
    className: "com.digitalpebble.stormcrawler.bolt.JSoupParserBolt" 
    parallelism: 1

  - id: "index"
    className: "com.digitalpebble.stormcrawler.elasticsearch.bolt.IndexerBolt"
    parallelism: 1
    configMethods:
      - name: "withConfigFile"
        args:
          - "es-conf.yaml"

  - id: "status"
    className: "com.digitalpebble.SQLStatusUpdaterBolt"
    parallelism: 1

  - id: "debug"
    className: "com.digitalpebble.DebugBolt"
    parallelism: 1

streams:
  - from: "spout"
    to: "partitioner"
    grouping:
      type: SHUFFLE

  - from: "spout"
    to: "debug" 
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

  - from: "fetcher"
    to: "status"
    grouping:
      type: LOCAL_OR_SHUFFLE
      streamId: "status"

  - from: "sitemap"
    to: "status"
    grouping:
      type: LOCAL_OR_SHUFFLE
      streamId: "status"

  - from: "parse"
    to: "status"
    grouping:
      type: LOCAL_OR_SHUFFLE
      streamId: "status"

  - from: "index"
    to: "status"
    grouping:
      type: LOCAL_OR_SHUFFLE
      streamId: "status"
      type: LOCAL_OR_SHUFFLE
      streamId: "status"
      type: LOCAL_OR_SHUFFLE
      streamId: "status"
