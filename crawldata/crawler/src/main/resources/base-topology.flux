name: "base-topology"

includes:
  - resource: true
    file: "/crawler-conf.yaml"
    override: false

config:
  # Required configs that must be provided
  topology.workers: 1
  topology.message.timeout.secs: 300
  topology.max.spout.pending: 300
  topology.kryo.register:
    - com.digitalpebble.stormcrawler.Metadata
  
  # Oracle database configuration
  jdbc.connection.timeout.ms: 30000
  oracle.connection.pool.size: 5
  oracle.query.timeout: 30
  
  # SQL status storage configuration
  sql.connection.string: "jdbc:oracle:thin:@//oracle-test:1521/XE"
  sql.user: "c##mojtaba"
  sql.password: "bjnSY55l0g1IrzWY71Jg"
  sql.status.table: "crawl_queue"
  sql.max.retries: 3
  sql.retry.interval.ms: 2000
  sql.show.sql: true

  # throttle outlinks (if inherited)
  parser.emitOutlinks: false
  jsoupfilters.config.file: "jsoupfilters.json"

  # Fallbacks (will be overridden by crawler-conf.yaml include)
  http.agent.name: "StormCrawler Enterprise"
  es.indexer.addresses: ["http://elasticsearch:9200"]

spouts:
  - id: "spout"
    className: "com.digitalpebble.SimpleOracleSpout"
    parallelism: 1
    # (Relies on -c sql.* passed at submission or included config)

bolts:
  - id: "fetcher"
    className: "com.digitalpebble.stormcrawler.bolt.FetcherBolt"
    parallelism: 1
  - id: "sitemap"
    className: "com.digitalpebble.stormcrawler.bolt.SiteMapParserBolt"
    parallelism: 1
  - id: "parse"
    className: "com.digitalpebble.stormcrawler.bolt.JSoupParserBolt"
    parallelism: 1
  - id: "indexer"
    className: "com.digitalpebble.stormcrawler.elasticsearch.bolt.IndexerBolt"
    parallelism: 1
  - id: "status"
    className: "com.digitalpebble.SQLStatusUpdaterBolt"
    parallelism: 2
  - id: "extractor"
    className: "com.digitalpebble.ParsedMetadataBolt"
    parallelism: 1

streams:
  # Correct ingestion + fetch
  - from: "spout"
    to: "fetcher"
    grouping:
      type: SHUFFLE

  # Fetcher -> sitemap
  - from: "fetcher"
    to: "sitemap"
    grouping:
      type: LOCAL_OR_SHUFFLE

  # Fetcher -> extractor (replace direct fetcher->parse)
  - from: "fetcher"
    to: "extractor"
    grouping:
      type: LOCAL_OR_SHUFFLE

  # Extractor -> parse
  - from: "extractor"
    to: "parse"
    grouping:
      type: LOCAL_OR_SHUFFLE

  # Sitemap -> parse
  - from: "sitemap"
    to: "parse"
    grouping:
      type: LOCAL_OR_SHUFFLE

  # Parse -> indexer
  - from: "parse"
    to: "indexer"
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
  - from: "indexer"
    to: "status"
    grouping:
      type: LOCAL_OR_SHUFFLE
      streamId: "status"