name: "crawler"

spouts:
  - id: "spout"
    className: "com.digitalpebble.SimpleOracleSpout"
    parallelism: 1

config:
  # Basic crawler configuration
  topology.workers: 1
  topology.message.timeout.secs: 300
  topology.max.spout.pending: 300
  topology.debug: false
  
  # Fetcher configuration
  fetcher.threads.number: 10
  fetcher.server.delay: 1.0
  fetcher.max.crawl.delay: 30
  
  # Parser configuration
  jsoupfilters.config.file: "jsoupfilters.json"
  urlfilters.config.file: "urlfilters.json"
  
  # Status updater configuration
  status.updater.cache.spec: "maximumSize=500000,expireAfterAccess=1h"
  
  # Oracle database configuration
  sql.connection.string: "jdbc:oracle:thin:@//oracle-test:1521/XE"
  sql.user: "c##mojtaba"
  sql.password: "bjnSY55l0g1IrzWY71Jg"
  sql.status.table: "crawl_queue"
  sql.max.retries: 3
  sql.retry.interval.ms: 2000
  sql.show.sql: true

  # User-Agent configuration
  http.agent.name: "Mozilla/5.0 (compatible; StormCrawler/2.0; +https://stormcrawler.net)"
  
  # Elasticsearch configuration for content indexing
  es.indexer.addresses: ["http://elasticsearch:9200"]
  es.indexer.index.name: "content"
  es.indexer.create: true
  es.indexer.doc.type: "_doc"
  es.indexer.flushInterval: "5s"
  es.indexer.bulkActions: 50
  es.indexer.bulkSize: "5mb"
  es.indexer.concurrentRequests: 1
  indexer.url.fieldname: "url"
  indexer.text.fieldname: "text"
  indexer.md.mapping:
    - parse.title=title
    - parse.description=description
    - parse.keywords=keywords
    - parse.author=author
    - parse.publishedDate=publishedDate
    - parse.lastModified=lastModified
    - canonical=canonical
  
  # Connection settings
  es.client.connection.timeout: 10000
  es.client.socket.timeout: 10000
  es.client.max.connections.per.route: 20
  es.client.max.connections.total: 100

  # Crawler-specific settings
  parser.emitOutlinks: false
  spout.fetch.batch: 80
  spout.min.queue.size: 15
  spout.fetch.interval.ms: 6000
  spout.select.lock.rows: true
  status.fetch.delay.mins: 1440
  status.error.retry.mins: 30

  # Protocol implementations
  http.protocol.implementation: "com.digitalpebble.stormcrawler.protocol.httpclient.HttpProtocol"
  https.protocol.implementation: "com.digitalpebble.stormcrawler.protocol.httpclient.HttpProtocol"

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
    parallelism: 2

  - id: "debug"
    className: "com.digitalpebble.DebugBolt"
    parallelism: 1

  - id: "extractor"
    className: "com.digitalpebble.ParsedMetadataBolt"
    parallelism: 1

streams:
  # Spout -> partitioner (+ debug)
  - from: "spout"
    to: "partitioner"
    grouping:
      type: SHUFFLE
  - from: "spout"
    to: "debug"
    grouping:
      type: SHUFFLE

  # Partitioner -> fetcher
  - from: "partitioner"
    to: "fetcher"
    grouping:
      type: FIELDS
      args: ["key"]

  # Fetcher -> sitemap and extractor
  - from: "fetcher"
    to: "sitemap"
    grouping:
      type: LOCAL_OR_SHUFFLE
  - from: "fetcher"
    to: "extractor"
    grouping:
      type: LOCAL_OR_SHUFFLE

  # Extractor -> parse; Sitemap -> parse
  - from: "extractor"
    to: "parse"
    grouping:
      type: LOCAL_OR_SHUFFLE
  - from: "sitemap"
    to: "parse"
    grouping:
      type: LOCAL_OR_SHUFFLE

  # Parse -> index
  - from: "parse"
    to: "index"
    grouping:
      type: LOCAL_OR_SHUFFLE

  # Status side-streams
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
    grouping:
      type: LOCAL_OR_SHUFFLE
      streamId: "status"

  - from: "index"
    to: "status"
    grouping:
      type: LOCAL_OR_SHUFFLE
      streamId: "status"
      streamId: "status"
    grouping:
      type: LOCAL_OR_SHUFFLE
      streamId: "status"

  - from: "index"
    to: "status"
    grouping:
      type: LOCAL_OR_SHUFFLE
      streamId: "status"
      streamId: "status"
