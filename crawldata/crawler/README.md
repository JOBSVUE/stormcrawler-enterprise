# StormCrawler Example

This is a complete web crawler application built with StormCrawler and Elasticsearch integration.

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
