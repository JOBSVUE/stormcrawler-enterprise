# StormCrawler Example

This is a complete web crawler application built with StormCrawler and Elasticsearch integration.

# Important:
Seeds are the starting URLs of a crawl.
- Concept: The initial set of URLs the crawler is given to begin exploration. All depth calculations are measured from these URLs.
- Depth: Seeds are depth 0 (unless explicitly stored/emitted with another depth). Any outlink from a seed becomes depth 1, and so on.
- In this project: The spout is SimpleOracleSpout, so seeds are rows in the Oracle table (crawl_queue) with status NEW or DISCOVERED and due nextfetchdate. Those rows are emitted into the topology as the initial frontier.
- How to add: Insert rows into crawl_queue (see README’s SQL example). If you store a depth column and the spout reads it, set it to 0. If not stored, the emitted metadata.depth typically defaults to 0.
- Relation to emitOutlinks and max depth:
  - parser.emitOutlinks controls whether HTML links from fetched pages are emitted (creating depth 1 from seed pages, depth 2 from those, etc.).
  - spout.max.depth discards any URL whose depth exceeds the configured limit before it’s enqueued/fetched.
- Sitemaps: With sitemap.discovery enabled, the crawler can discover sitemap URLs starting from your seeds (e.g., via robots.txt) and parse them. URLs found in sitemaps are then subject to the same depth and filter rules as any other discovered URL.

## Project Structure

```
crawler/
├── pom.xml                           # Maven configuration
├── crawler.flux                      # Flux topology definition
├── src/
│   ├── main/
│   │   ├── java/                     # Java source files
│   │   │   └── com/digitalpebble/
│   │   │       └── *.java
│   │   └── resources/                # Configuration files
│   │       ├── crawler-conf.yaml     # Main crawler configuration
│   │       ├── es-conf.yaml          # Elasticsearch configuration
│   │       ├── parsefilters.json     # Parse filters configuration
│   │       ├── urlfilters.json       # URL filters configuration
│   │       ├── default-regex-filters.txt # URL filtering rules
│   │       └── logback.xml           # Logging configuration
```

## Building and Running

1. **Build the project**:

   ```bash
   cd crawler
   mvn clean package
   ```

2. **Run locally**:

   ```bash
   java -jar target/stormcrawler-example-1.0-SNAPSHOT.jar --local crawler.flux
   ```

   Or using Maven:

   ```bash
   mvn exec:java@run-local
   ```

3. **Submit to Storm cluster**:

   ```bash
   storm jar target/stormcrawler-example-1.0-SNAPSHOT.jar org.apache.storm.flux.Flux crawler.flux --remote
   ```

4. **Seed URLs**:

   To add seed URLs to the crawler, use the Elasticsearch API:

   ```bash
   curl -XPOST http://elasticsearch:9200/status/_doc/ -H 'Content-Type: application/json' -d '
   {
     "url": "https://example.org/",
     "status": "DISCOVERED",
     "metadata": {
       "depth": "0"
     },
     "nextFetchDate": "2023-01-01T00:00:00.000Z"
   }'
   ```

## Seeding (Oracle backend)
Insert seed rows into crawl_queue (status NEW or DISCOVERED):

```sql
INSERT INTO crawl_queue (url, status, nextfetchdate) VALUES ('https://example.org/', 'NEW', SYSTIMESTAMP);
COMMIT;
```

The SimpleOracleSpout selects rows with status NEW/DISCOVERED and (nextfetchdate IS NULL OR <= now).

## Runtime DB overrides
You can override JDBC settings at submission:

```bash
export JDBC_URL="jdbc:oracle:thin:@//oracle-test:1521/XE"
export JDBC_USER="c##mojtaba"
export JDBC_PASS="***"
./submit-topology.sh
```

## Configuration

The crawler behavior is controlled by the following configuration files:

- **crawler-conf.yaml**: Main configuration for the crawler
- **es-conf.yaml**: Elasticsearch specific settings
- **parsefilters.json**: Rules for extracting content from HTML
- **urlfilters.json**: Rules for filtering URLs to crawl
- **default-regex-filters.txt**: Regex patterns for URL filtering

## Performance & Tuning

Key knobs (can be passed with -c or set in flux):
- spout.fetch.batch : how many DB rows per pull (default 50–100)
- spout.min.queue.size : trigger refill when queue below threshold
- spout.fetch.interval.ms : minimum ms between DB fetches
- spout.select.lock.rows=true : uses FOR UPDATE SKIP LOCKED (Oracle 12c+) to avoid contention
- parser.emitOutlinks.max.per.page : limit outlink fan‑out (reduce DB churn)
- status.fetch.delay.mins / status.error.retry.mins : control nextfetchdate progression

Symptoms & remedies:
- High spout complete latency: increase topology.max.spout.pending, add fetcher/parse parallelism.
- Many ERROR status early: inspect network / robots; error retry delay keeps DB cleaner.
- DB hot updates: lower outlink max, increase batch size, enable row locking (default).

## Security

Move sql.password out of flux/YAML into environment:
export JDBC_PASS='******'
storm jar ... -c sql.password="$JDBC_PASS"

## Prerequisites

- Java 11+
- Apache Storm (for cluster deployment)
- Elasticsearch 7.17.7 (for storage)

Note: This example uses Elasticsearch for storage. Make sure Elasticsearch is running at the configured address (default: elasticsearch:9200).

## Parsing Enhancements
- Updated jsoupfilters.json to narrow text extraction (ARTICLE/MAIN/SECTION + content divs).
- Added exclusion of javascript:, mailto:, tel:, fragment-only links in link extraction XPath.
- Extended date & author extraction (og:updated_time, itemprop dates).
- Added lastModified metadata field.
- Removed explicit jsoup dependency; now using StormCrawler’s tested version (1.16.1 via 2.10).

## Data Flow Architecture

```mermaid
flowchart TD
  subgraph Storage
    ORA[(Oracle\ncrawl_queue)]
    ES[(Elasticsearch\nindex: content)]
  end

  Spout[SimpleOracleSpout\n(reads NEW/DISCOVERED)] --> Fetcher[FetcherBolt]
  Fetcher -->|sitemaps| Sitemap[SiteMapParserBolt]
  Fetcher --> Parse[JSoupParserBolt]
  Sitemap --> Parse
  Parse --> Extractor[ParsedMetadataBolt\n(Renderer->Extractor)]
  Extractor --> Indexer[IndexerBolt]
  Indexer --> ES

  %% Status side-streams
  Fetcher -. status .-> Status[SQLStatusUpdaterBolt]
  Sitemap -. status .-> Status
  Parse -. status .-> Status
  Indexer -. status .-> Status
  Status --> ORA

  %% Optional (in crawler.flux)
  Spout -. optional .-> Partitioner[URLPartitionerBolt]
  Partitioner -. optional .-> Fetcher
```

Legend:
- SimpleOracleSpout selects URLs from Oracle with status NEW/DISCOVERED and due nextfetchdate.
- ParsedMetadataBolt calls the external extractor service and enriches Metadata.
- JSoupParserBolt performs parsing/metadata extraction.
- IndexerBolt writes documents to Elasticsearch.
- SQLStatusUpdaterBolt consumes status side-streams and upserts into Oracle (nextfetchdate backoff).

Notes:
- parser.emitOutlinks=false with spout.max.depth=0; no outlink expansion beyond seeds.
- URLPartitionerBolt is present in crawler.flux (optional), not in base-topology.flux.

## Crawler behavior summary

- URL filtering:
  - Active link pattern excludes javascript:, mailto:, tel:, and fragment-only links (see jsoupfilters.json).
  - No urlfilters.json provided in repo; allow/deny rules beyond length/path repetition are unknown. Sitemaps are still processed.
  - default-regex-normalizers.xml rules are commented out, so no URL normalization (e.g., session IDs, fragments) is applied.

- Content processing (JSoupParserBolt):
  - Extracts: canonical, parse.title, parse.description, parse.keywords, parse.author, parse.publishedDate, parse.lastModified.
  - Emits main text as “text” (mapped by indexer.text.fieldname).

- Crawl depth:
  - Page link expansion is disabled (parser.emitOutlinks=false).
  - Depth is limited to 0 via spout.max.depth=0.

- Outlink emission:
  - Disabled for page parsing (no outlinks emitted from HTML pages).
  - Sitemap discoveries still flow on the “status” stream.

- Ambiguities / TODO:
  - Provide urlfilters.json if you need host/path allow/deny rules.
  - Enable regex normalizers if you want to strip fragments/session IDs.
  - parsefilters.json is present but JSoupParserBolt uses jsoupfilters.json; keep both consistent if you ever switch parsers.

## Crawl depth policy (TL;DR)

- Current depth: 0
  - Enforced by parser.emitOutlinks=false and spout.max.depth=0 (see crawler-conf.yaml).
  - HTML pages do not emit outlinks.
  - Sitemap URLs discovered by SiteMapParserBolt are still accepted and treated like seeds.
- To enable deeper crawls: set parser.emitOutlinks=true and raise spout.max.depth accordingly.
- To enable deeper crawls: set parser.emitOutlinks=true and raise spout.max.depth accordingly.
