name: "base-topology"

spouts:
  - id: "spout"
    className: "com.digitalpebble.SimpleOracleSpout"
    parallelism: 1

config:
  # Required configs that must be provided
  topology.workers: 1
  topology.message.timeout.secs: 300
  topology.max.spout.pending: 200
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

bolts:
  - id: "indexer"
    className: "com.digitalpebble.stormcrawler.elasticsearch.bolt.IndexerBolt"
    parallelism: 1
    
  - id: "status"
    className: "com.digitalpebble.stormcrawler.elasticsearch.bolt.StatusUpdaterBolt"
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

streams:
  - from: "spout"
    to: "parse"
    grouping:
      type: SHUFFLE

  - from: "parse"
    to: "status"
    grouping:
      type: SHUFFLE

  - from: "status"
    to: "indexer" 
    grouping:
      type: SHUFFLE