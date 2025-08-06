name: "varzesh3-news-crawler"

spouts:
  - id: "spout"
    className: "com.digitalpebble.stormcrawler.spout.FileSpout"
    constructorArgs:
      - "seeds"     # directory containing my .txt files
      - "url"       
      - false       # cycle

bolts:
  - id: "partitioner"
    className: "com.digitalpebble.stormcrawler.bolt.URLPartitionerBolt"
    parallelism: 1

  - id: "fetcher"
    className: "com.digitalpebble.stormcrawler.bolt.FetcherBolt"
    parallelism: 5

  - id: "sitemap"
    className: "com.digitalpebble.stormcrawler.bolt.SiteMapParserBolt"
    parallelism: 1

  - id: "parser"
    className: "com.digitalpebble.stormcrawler.bolt.JSoupParserBolt"
    parallelism: 2

  - id: "indexer"
    className: "com.digitalpebble.stormcrawler.elasticsearch.bolt.IndexerBolt"
    parallelism: 1

  - id: "status"
    className: "com.digitalpebble.stormcrawler.persistence.SQLStatusUpdaterBolt"
    constructorArgs:
      - "oracle.jdbc.OracleDriver"
      - "jdbc:oracle:thin:@oracle-test:1521/XE"
      - "c##mojtaba"
      - "bjnSY55l0g1IrzWY71Jg"
      - "UPDATE crawl_queue SET status = ?, last_fetch_ts = SYSTIMESTAMP WHERE url = ?"
    parallelism: 2

  - id: "debug"
    className: "com.digitalpebble.DebugBolt"
    parallelism: 1

streams:
  - from: "spout"
    to: "debug"
    grouping:
      type: SHUFFLE

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

  - from: "fetcher"
    to: "parser"
    grouping:
      type: LOCAL_OR_SHUFFLE

  - from: "sitemap"
    to: "parser"
    grouping:
      type: LOCAL_OR_SHUFFLE

  - from: "parser"
    to: "indexer"
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

  - from: "parser"
    to: "status"
    grouping:
      type: LOCAL_OR_SHUFFLE
      streamId: "status"

  - from: "indexer"
    to: "status"
    grouping:
      type: LOCAL_OR_SHUFFLE
      streamId: "status"

config:
  http.agent.name:        "varzesh3-news-crawler"
  http.agent.version:     "1.0"
  http.agent.description: "My StormCrawler news bot"
  http.agent.url:         "http://varzesh3.com"
  http.agent.email:       "bot@varzesh3.com"
  
  # — Nimbus & Storm basics —
  nimbus.seeds:
    - "nimbus"
  nimbus.thrift.port: 6627
  topology.workers: 2
  topology.message.timeout.secs: 300
  topology.max.spout.pending: 250
  topology.debug: false

  # — Kryo registrations —
  topology.kryo.register:
    - "com.digitalpebble.stormcrawler.Metadata"
    - "java.util.Collections$EmptyMap"
    - "org.apache.storm.shade.net.minidev.json.JSONObject"

  # — Elasticsearch indexer only (removed status config) —
  es.indexer.addresses: ["http://elasticsearch:9200"]
  es.indexer.index.name: "content"
  es.indexer.doc.type: "_doc"
  es.indexer.create: false
  es.indexer.settings:
    cluster.name: "elasticsearch"

  # — HTTP fetcher —
  fetcher.threads.number: 50
  fetcher.server.delay: 1.0
  fetcher.server.min.delay: 0.0
  fetcher.max.crawl.delay: 30
  http.timeout: 10000
  http.content.limit: 65536
  http.store.responsetime: true
  http.skip.robots: false

  # — FileSpout configuration —
  spout.absolutepath: false
  fileSpout.dir: "seeds"
  fileSpout.file: "urls.txt"
  
  # — Filters —
  urlfilters.config.file: "urlfilters.json"
  parsefilters.config.file: "parsefilters.json"

  # — Scheduler & StatusUpdater —
  status.updater.cache.spec: "maximumSize=500000,expireAfterAccess=1h"
  status.updater.use.cache: true
  status.updater.unit.round.date: "SECONDS"
  scheduler.class: "com.digitalpebble.stormcrawler.persistence.DefaultScheduler"

  # — Metrics consumer —
  
  # — URL Filters —
  urlfilters:
    - class: "com.digitalpebble.stormcrawler.filtering.regex.RegexURLFilter"
      name: "RegexURLFilter"
      params:
        file: "urlfilters.json"

  # — Parse Filters —
  parsefilters:
    - class: "com.digitalpebble.stormcrawler.parse.filter.ContentFilter"
      name: "ContentFilter"
      params:
        pattern: "//DIV[@id=\"maincontent\"]"
        key: "content"
    - class: "com.digitalpebble.stormcrawler.parse.filter.XPathFilter"
      name: "XPathFilter"
      params:
        - key: "title"
          pattern: "//TITLE"
        - key: "description"
          pattern: "//META[@name=\"description\"]/@content"
        - key: "keywords"
          pattern: "//META[@name=\"keywords\"]/@content"