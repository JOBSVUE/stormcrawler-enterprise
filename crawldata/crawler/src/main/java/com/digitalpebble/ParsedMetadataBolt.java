package com.digitalpebble;

import com.digitalpebble.stormcrawler.Metadata;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

// Use standard Jackson (provided by crawler/pom.xml)
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.apache.storm.tuple.Tuple;
// Storm bolt imports
import org.apache.storm.topology.base.BaseRichBolt;
import org.apache.storm.task.OutputCollector;
import org.apache.storm.task.TopologyContext;
import org.apache.storm.topology.OutputFieldsDeclarer;
import org.apache.storm.tuple.Fields;
import org.apache.storm.tuple.Values;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.Charset;
import java.time.Duration;
import java.util.Map;

/**
 * JSoupFilter that synchronously calls the external FastAPI extractor (trafilatura)
 * with the page HTML and updates the ParseResult text and Metadata accordingly.
 *
 * Config keys:
 *  - extractor.service.url (default: http://extractor:8000/extract)
 *  - extractor.timeout.ms (default: 15000)
 *  - extractor.min.extracted.chars (default: 50)
 */
public class ParsedMetadataBolt extends BaseRichBolt {

    private static final Logger LOG = LoggerFactory.getLogger(ParsedMetadataBolt.class);

    private transient HttpClient http;
    private transient ObjectMapper mapper;
    private transient OutputCollector collector;

    private String extractorUrl;
    private int timeoutMs;
    private int minChars;

    @Override
    public void prepare(Map<String, Object> stormConf, TopologyContext context, OutputCollector collector) {
        this.collector = collector;
        // Init HTTP client & mapper
        this.http = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();
        this.mapper = new ObjectMapper();

        // use existing helpers
        this.extractorUrl = getString(stormConf, "extractor.service.url", "http://extractor:8000/extract");
        this.timeoutMs = getInt(stormConf, "extractor.timeout.ms", 15000);
        this.minChars = getInt(stormConf, "extractor.min.extracted.chars", 50);

        LOG.info("External extractor bolt configured. extractorUrl={}, timeoutMs={}, minChars={}",
                extractorUrl, timeoutMs, minChars);
    }

    @Override
    public void execute(Tuple tuple) {
        String url = safeGetString(tuple, "url");
        Metadata metadata = safeGetMetadata(tuple, "metadata");

        if (url == null) {
            LOG.warn("No URL found in tuple, failing");
            collector.fail(tuple);
            return;
        }

        String html = readHtml(tuple, metadata);
        if (html == null || html.isEmpty()) {
            LOG.debug("Empty HTML for URL {}, passing through", url);
            collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
            collector.ack(tuple);
            return;
        }

        try {
            String payload = toJsonPayload(url, html);
            HttpRequest req = HttpRequest.newBuilder(URI.create(extractorUrl))
                    .timeout(Duration.ofMillis(timeoutMs))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(payload))
                    .build();

            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            int code = resp.statusCode();

            if (code == 200) {
                JsonNode root = mapper.readTree(resp.body());
                String content = textOrNull(root, "content");
                String title = textOrNull(root, "title");

                if (content != null && content.length() >= minChars) {
                    byte[] extractedBytes = content.getBytes(detectCharset(metadata));
                    if (title != null && !title.isBlank()) {
                        metadata.addValue("parse.title", title);
                    }
                    metadata.addValue("extraction.method", "trafilatura");
                    collector.emit(tuple, new Values(url, extractedBytes, metadata));
                } else {
                    LOG.debug("Extractor returned too-short/empty content for URL {}", url);
                    collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
                }
            } else if (code == 204) {
                LOG.debug("Extractor 204 No Content for URL {}", url);
                collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
            } else {
                LOG.warn("Extractor HTTP {} for URL {}. Body: {}", code, url, resp.body());
                collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
            }
            collector.ack(tuple);
        } catch (Exception e) {
            LOG.warn("Extractor call failed for URL {}: {}", url, e.toString());
            collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
            collector.ack(tuple);
        }
    }

    @Override
    public void declareOutputFields(OutputFieldsDeclarer declarer) {
        declarer.declare(new Fields("url", "content", "metadata"));
    }

    /**
     * Utility: returns text value from JsonNode or null.
     */
    private static String textOrNull(JsonNode root, String key) {
        JsonNode n = root.get(key);
        return n != null && !n.isNull() ? n.asText() : null;
    }

    /**
     * Utility: get string from config map with default.
     */
    private static String getString(Map<String, Object> conf, String key, String def) {
        Object v = conf.get(key);
        return v != null ? String.valueOf(v) : def;
    }

    /**
     * Utility: get int from config map with default.
     */
    private static int getInt(Map<String, Object> conf, String key, int def) {
        Object v = conf.get(key);
        if (v == null) return def;
        try {
            return Integer.parseInt(String.valueOf(v));
        } catch (Exception e) {
            return def;
        }
    }

    /**
     * Escape string for minimal JSON building.
     */
    private static String escape(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r");
    }

    /**
     * Minimal JSON payload builder.
     */
    private static String toJsonPayload(String url, String html) {
        // Minimal JSON builder
        return "{\"url\":\"" + escape(url) + "\",\"html_content\":\"" + escape(html) + "\"}";
    }

    /**
     * Safely retrieve a String from a Tuple by field name.
     */
    private static String safeGetString(Tuple t, String field) {
        try {
            int idx = t.fieldIndex(field);
            if (idx >= 0) return t.getStringByField(field);
        } catch (Exception ignored) {
        }
        return null;
    }

    /**
     * Safely retrieve Metadata from a Tuple by field name.
     */
    private static Metadata safeGetMetadata(Tuple t, String field) {
        try {
            int idx = t.fieldIndex(field);
            if (idx >= 0) {
                Object v = t.getValueByField(field);
                if (v instanceof Metadata) return (Metadata) v;
            }
        } catch (Exception ignored) {
        }
        return new Metadata();
    }

    /**
     * Read HTML content from a Tuple (prefer raw bytes from 'content' field).
     */
    private static String readHtml(Tuple t, Metadata md) {
        // Prefer raw HTML bytes from 'content'
        try {
            int idx = t.fieldIndex("content");
            if (idx >= 0) {
                Object v = t.getValue(idx);
                if (v instanceof byte[]) {
                    byte[] bytes = (byte[]) v;
                    Charset cs = detectCharset(md);
                    return new String(bytes, cs);
                } else if (v instanceof String) {
                    return (String) v;
                }
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    /**
     * Detect charset from Metadata using common header keys.
     */
    private static Charset detectCharset(Metadata md) {
        String[] keys = new String[]{
                "charset", "parse.charset", "parse.Content-Encoding", "Content-Encoding", "Content-Type"
        };
        for (String k : keys) {
            String val = md.getFirstValue(k);
            if (val != null) {
                // very light parsing for Content-Type: text/html; charset=UTF-8
                int i = val.toLowerCase().indexOf("charset=");
                if (i >= 0) {
                    try {
                        return Charset.forName(val.substring(i + 8).trim());
                    } catch (Exception ignored) {
                    }
                }
                try {
                    return Charset.forName(val.trim());
                } catch (Exception ignored) {
                }
            }
        }
        return Charset.forName("UTF-8");
    }
}
