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

## Configuration

The crawler behavior is controlled by the following configuration files:

- **crawler-conf.yaml**: Main configuration for the crawler
- **es-conf.yaml**: Elasticsearch specific settings
- **parsefilters.json**: Rules for extracting content from HTML
- **urlfilters.json**: Rules for filtering URLs to crawl
- **default-regex-filters.txt**: Regex patterns for URL filtering

## Prerequisites

- Java 11+
- Apache Storm (for cluster deployment)
- Elasticsearch 7.17.7 (for storage)

Note: This example uses Elasticsearch for storage. Make sure Elasticsearch is running at the configured address (default: elasticsearch:9200).
