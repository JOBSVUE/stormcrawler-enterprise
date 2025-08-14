package com.digitalpebble;

import com.digitalpebble.stormcrawler.Metadata;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

// Use standard Jackson (provided by crawler/pom.xml)
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

// Storm bolt imports
import org.apache.storm.tuple.Tuple;
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
    private int maxHtmlChars; // new: cap HTML size sent to extractor

    // new: renderer chain endpoint
    private String rendererUrl;
    private int rendererTimeoutMs;

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
        this.maxHtmlChars = getInt(stormConf, "extractor.max.html.chars", 900000);

        // prefer renderer chain if configured
        this.rendererUrl = getString(stormConf, "renderer.service.url", null);
        this.rendererTimeoutMs = getInt(stormConf, "renderer.timeout.ms", 30000);

        LOG.info("External extractor bolt configured. extractorUrl={}, timeoutMs={}, minChars={}, maxHtmlChars={}, rendererUrl={}, rendererTimeoutMs={}",
                extractorUrl, timeoutMs, minChars, maxHtmlChars, rendererUrl, rendererTimeoutMs);
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
            metadata.addValue("extraction.method", "fallback");
            metadata.addValue("extraction.reason", "empty_html");
            collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
            collector.ack(tuple);
            return;
        }

        // Record input info
        String ctype = firstNonEmpty(
                metadata.getFirstValue("Content-Type"),
                metadata.getFirstValue("parse.Content-Type"),
                metadata.getFirstValue("http.content.type"));
        if (ctype != null) metadata.addValue("extraction.input.contentType", ctype);

        // Skip non-HTML content (e.g., PDFs, images)
        if (ctype != null && !ctype.toLowerCase().contains("html") && !ctype.toLowerCase().contains("xml")) {
            metadata.addValue("extraction.method", "fallback");
            metadata.addValue("extraction.reason", "non_html_content");
            collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
            collector.ack(tuple);
            return;
        }

        // Basic heuristic: ensure it's likely HTML
        boolean looksHtml = html.indexOf('<') >= 0; // cheap check
        if (!looksHtml) {
            metadata.addValue("extraction.method", "fallback");
            metadata.addValue("extraction.reason", "content_not_html_like");
            collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
            collector.ack(tuple);
            return;
        }

        // Sanitize NULs/control that may break JSON parsers
        if (html.indexOf('\u0000') >= 0) {
            html = html.replace("\u0000", "");
        }

        // Cap very large HTML payloads to avoid 400 from extractor
        boolean truncated = false;
        if (html.length() > maxHtmlChars) {
            html = html.substring(0, maxHtmlChars);
            truncated = true;
        }
        metadata.addValue("extraction.input.length", Integer.toString(html.length()));
        if (truncated) {
            metadata.addValue("extraction.truncated", "true");
        }

        try {
            // If renderer chain is set, call it with just the URL, letting the service render + extract.
            if (rendererUrl != null && !rendererUrl.isBlank()) {
                String payload = buildRendererPayload(url, metadata);
                HttpRequest req = HttpRequest.newBuilder(URI.create(rendererUrl))
                        .timeout(Duration.ofMillis(rendererTimeoutMs))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(payload))
                        .build();

                HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
                int code = resp.statusCode();

                if (code == 200) {
                    JsonNode root = mapper.readTree(resp.body());
                    String content = textOrNull(root, "content");
                    String title = textOrNull(root, "title");
                    String seoDesc = textOrNull(root, "seo_description");
                    String companyId = textOrNull(root, "company_id");
                    if (companyId == null || companyId.isBlank()) companyId = url;
                    if (companyId != null) metadata.addValue("company_id", companyId);
                    if (seoDesc != null && !seoDesc.isBlank()) {
                        metadata.addValue("seo_description", seoDesc);
                        // also copy to parse.description to reuse existing ES mapping -> description
                        metadata.addValue("parse.description", seoDesc);
                    }
                    // NEW: keywords array -> parse.keywords
                    JsonNode kws = root.get("keywords");
                    if (kws != null && kws.isArray()) {
                        for (JsonNode kn : kws) {
                            String kw = kn != null ? kn.asText(null) : null;
                            if (kw != null && !kw.isBlank()) metadata.addValue("parse.keywords", kw);
                        }
                    }
                    if (content != null && content.length() >= minChars) {
                        byte[] extractedBytes = content.getBytes(detectCharset(metadata));
                        if (title != null && !title.isBlank()) {
                            metadata.addValue("parse.title", title);
                        }
                        // optional: mirror main content into a metadata field for separate indexing
                        metadata.addValue("contents", content);
                        metadata.addValue("extraction.method", "renderer+trafilatura");
                        metadata.addValue("extraction.length", Integer.toString(content.length()));
                        metadata.addValue("extraction.status", "200");
                        collector.emit(tuple, new Values(url, extractedBytes, metadata));
                    } else {
                        LOG.debug("Renderer chain returned too-short/empty content for URL {}", url);
                        metadata.addValue("extraction.method", "fallback");
                        metadata.addValue("extraction.reason", "too_short_or_empty");
                        metadata.addValue("extraction.status", "200");
                        collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
                    }
                    collector.ack(tuple);
                    return;
                } else if (code == 204) {
                    LOG.debug("Renderer chain 204 No Content for URL {}", url);
                    metadata.addValue("extraction.method", "fallback");
                    metadata.addValue("extraction.reason", "http_204");
                    metadata.addValue("extraction.status", "204");
                    collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
                    collector.ack(tuple);
                    return;
                } else {
                    LOG.warn("Renderer chain HTTP {} for URL {}. Body: {}", code, url, resp.body());
                    // fall through to extractor fallback
                }
            }

            // Fallback: call extractor directly with already-fetched HTML
            String payload = toJsonPayload(url, html, metadata);
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
                String seoDesc = textOrNull(root, "seo_description");
                String companyId = textOrNull(root, "company_id");
                if (companyId == null || companyId.isBlank()) companyId = url;
                if (companyId != null) metadata.addValue("company_id", companyId);
                if (seoDesc != null && !seoDesc.isBlank()) {
                    metadata.addValue("seo_description", seoDesc);
                    metadata.addValue("parse.description", seoDesc);
                }
                // NEW: keywords array -> parse.keywords
                JsonNode kws = root.get("keywords");
                if (kws != null && kws.isArray()) {
                    for (JsonNode kn : kws) {
                        String kw = kn != null ? kn.asText(null) : null;
                        if (kw != null && !kw.isBlank()) metadata.addValue("parse.keywords", kw);
                    }
                }
                if (content != null && content.length() >= minChars) {
                    byte[] extractedBytes = content.getBytes(detectCharset(metadata));
                    if (title != null && !title.isBlank()) {
                        metadata.addValue("parse.title", title);
                    }
                    // optional: mirror main content into a metadata field for separate indexing
                    metadata.addValue("contents", content);
                    metadata.addValue("extraction.method", "trafilatura");
                    metadata.addValue("extraction.length", Integer.toString(content.length()));
                    metadata.addValue("extraction.status", "200");
                    collector.emit(tuple, new Values(url, extractedBytes, metadata));
                } else {
                    LOG.debug("Extractor returned too-short/empty content for URL {}", url);
                    metadata.addValue("extraction.method", "fallback");
                    metadata.addValue("extraction.reason", "too_short_or_empty");
                    metadata.addValue("extraction.status", "200");
                    collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
                }
            } else if (code == 204) {
                LOG.debug("Extractor 204 No Content for URL {}", url);
                metadata.addValue("extraction.method", "fallback");
                metadata.addValue("extraction.reason", "http_204");
                metadata.addValue("extraction.status", "204");
                collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
            } else {
                LOG.warn("Extractor HTTP {} for URL {}. Body: {}", code, url, resp.body());
                metadata.addValue("extraction.method", "fallback");
                metadata.addValue("extraction.reason", "http_" + code);
                metadata.addValue("extraction.status", Integer.toString(code));
                collector.emit(tuple, new Values(url, tuple.getValueByField("content"), metadata));
            }
            collector.ack(tuple);
        } catch (Exception e) {
            LOG.warn("Extractor call failed for URL {}: {}", url, e.toString());
            metadata.addValue("extraction.method", "fallback");
            metadata.addValue("extraction.reason", "exception");
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
    private String toJsonPayload(String url, String html) {
        // Minimal JSON builder
        return "{\"url\":\"" + escape(url) + "\",\"html_content\":\"" + escape(html) + "\"}";
    }

    /**
     * Minimal JSON payload builder using Jackson; includes fetch_metadata hints if available.
     */
    private String toJsonPayload(String url, String html, Metadata md) {
        try {
            ObjectNode root = mapper.createObjectNode();
            root.put("url", url);
            root.put("html_content", html);

            // Optional: pass through a company_id if present in metadata
            String companyId = md.getFirstValue("company_id");
            if (companyId != null && !companyId.isBlank()) {
                root.put("company_id", companyId);
            }

            // Optional: send minimal fetch_metadata to improve title fallback on server
            ObjectNode fetchMeta = mapper.createObjectNode();
            String title = firstNonEmpty(md.getFirstValue("parse.title"), md.getFirstValue("title"));
            if (title != null && !title.isBlank()) fetchMeta.put("title", title);
            String contentType = firstNonEmpty(md.getFirstValue("Content-Type"), md.getFirstValue("parse.Content-Type"));
            if (contentType != null && !contentType.isBlank()) fetchMeta.put("content_type", contentType);
            String statusCode = md.getFirstValue("fetch.statusCode");
            if (statusCode != null && !statusCode.isBlank()) fetchMeta.put("statusCode", statusCode);
            Charset cs = detectCharset(md);
            if (cs != null) fetchMeta.put("charset", cs.displayName());
            if (!fetchMeta.isEmpty()) root.set("fetch_metadata", fetchMeta);

            return mapper.writeValueAsString(root);
        } catch (Exception e) {
            // Fallback to minimal JSON if serialization fails
            LOG.debug("Failed to build rich JSON payload, falling back: {}", e.toString());
            return toJsonPayload(url, html);
        }
    }

    // Small helper
    private static String firstNonEmpty(String... vals) {
        if (vals == null) return null;
        for (String v : vals) if (v != null && !v.isBlank()) return v;
        return null;
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

    /**
     * Build minimal renderer request payload.
     */
    private String buildRendererPayload(String url, Metadata md) {
        try {
            ObjectNode root = mapper.createObjectNode();
            root.put("url", url);

            // Optional: pass UA if present
            String ua = firstNonEmpty(md.getFirstValue("http.agent"), md.getFirstValue("User-Agent"));
            if (ua != null && !ua.isBlank()) root.put("user_agent", ua);

            // Optional: wait_for_selector could be configured via metadata if desired
            String selector = md.getFirstValue("renderer.wait_for_selector");
            if (selector != null && !selector.isBlank()) root.put("wait_for_selector", selector);

            // Optional: timeout override per URL
            String t = md.getFirstValue("renderer.timeout.ms");
            if (t != null) {
                try { root.put("timeout_ms", Integer.parseInt(t)); } catch (Exception ignore) {}
            }

            return mapper.writeValueAsString(root);
        } catch (Exception e) {
            LOG.debug("Failed to build renderer JSON payload, falling back: {}", e.toString());
            return "{\"url\":\"" + escape(url) + "\"}";
        }
    }
}
