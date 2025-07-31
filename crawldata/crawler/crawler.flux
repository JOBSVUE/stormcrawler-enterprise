name: "crawl"

spouts:
  - id: "spout"
    className: "com.digitalpebble.stormcrawler.spout.MemorySpout"
    constructorArgs:
      - ["https://www.yjc.ir/en/news/51305/stop-lying-muslim-advocacy-group-sues-facebook-over-claims-it-removes-hate-speech-hate-speech", "https://www.yjc.ir/en/news/50967/international-quran-competition-wraps-up-in-tehran"]
    parallelism: 1

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
    className: "com.digitalpebble.stormcrawler.elasticsearch.persistence.StatusUpdaterBolt"
    parallelism: 1

  - id: "deletion"
    className: "com.digitalpebble.stormcrawler.elasticsearch.bolt.DeletionBolt"
    parallelism: 1

streams:
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

  - from: "status"
    to: "deletion"
    grouping:
      type: LOCAL_OR_SHUFFLE
      streamId: "deletion"

config:
  topology.workers: 4
  topology.message.timeout.secs: 300
  topology.max.spout.pending: 250
  topology.debug: false
  topology.kryo.register:
    - "com.digitalpebble.stormcrawler.Metadata"
