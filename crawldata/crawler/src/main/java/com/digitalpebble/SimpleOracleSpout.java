package com.digitalpebble;

import org.apache.storm.spout.SpoutOutputCollector;
import org.apache.storm.task.TopologyContext;
import org.apache.storm.topology.OutputFieldsDeclarer;
import org.apache.storm.topology.base.BaseRichSpout;
import org.apache.storm.tuple.Fields;
import org.apache.storm.tuple.Values;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import com.digitalpebble.stormcrawler.Metadata;
import java.sql.*;
import java.util.Map;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.HashMap;

public class SimpleOracleSpout extends BaseRichSpout {
    private static final Logger LOG = LoggerFactory.getLogger(SimpleOracleSpout.class);

    private SpoutOutputCollector collector;
    private final LinkedBlockingQueue<String> queue = new LinkedBlockingQueue<>();
    private final Map<Object, String> pending = new HashMap<>();
    private String jdbcUrl;
    private String user;
    private String pass;
    private Connection connection;
    private boolean connectionInitialized = false;
    private long totalEmitted = 0;
    private long totalFetched = 0;
    private long lastLogTime = System.currentTimeMillis();
    private long lastFetchTime = 0;
    // Added missing configurable batch size holder
    private int fetchBatchSize = FETCH_BATCH_SIZE;
    // new tunables
    private int minQueueRefillThreshold = 10;
    private long fetchIntervalMs = FETCH_INTERVAL_MS;
    private boolean useRowLocking = true;

    // Optional: tune how many URLs to load in one fetch
    private static final int FETCH_BATCH_SIZE = 50;
    private static final long FETCH_INTERVAL_MS = 10000; // Fetch every 10 seconds

    // Configuration setter methods for Flux
    public void setJdbcUrl(String jdbcUrl) {
        this.jdbcUrl = jdbcUrl;
    }

    public void setJdbcUser(String user) {
        this.user = user;
    }

    public void setJdbcPassword(String pass) {
        this.pass = pass;
    }

    @Override
    public void open(Map<String, Object> conf, TopologyContext ctx, SpoutOutputCollector collector) {
        LOG.info("============= OPENING SIMPLE ORACLE SPOUT =============");
        this.collector = collector;
        
        this.jdbcUrl = firstNonEmpty(
                (String) conf.get("sql.connection.string"),
                System.getenv("JDBC_URL"),
                "jdbc:oracle:thin:@//oracle-test:1521/XE");
        this.user = firstNonEmpty(
                (String) conf.get("sql.user"),
                System.getenv("JDBC_USER"),
                "c##mojtaba");
        this.pass = firstNonEmpty(
                (String) conf.get("sql.password"),
                System.getenv("JDBC_PASS"));
        this.fetchBatchSize = parseIntOrDefault(
                conf.get("spout.fetch.batch"),
                System.getenv("SPOUT_FETCH_BATCH"),
                FETCH_BATCH_SIZE);
        this.minQueueRefillThreshold = parseIntOrDefault(
                conf.get("spout.min.queue.size"),
                System.getenv("SPOUT_MIN_QUEUE"),
                10);
        this.fetchIntervalMs = parseIntOrDefault(
                conf.get("spout.fetch.interval.ms"),
                System.getenv("SPOUT_FETCH_INTERVAL_MS"),
                (int) FETCH_INTERVAL_MS);
        this.useRowLocking = Boolean.parseBoolean(
                firstNonEmpty(
                        asString(conf.get("spout.select.lock.rows")),
                        System.getenv("SPOUT_LOCK_ROWS"),
                        "true"));
        LOG.info("Spout tuning: batchSize={}, minQueueRefill={}, fetchIntervalMs={}, rowLocking={}",
                fetchBatchSize, minQueueRefillThreshold, fetchIntervalMs, useRowLocking);
        
        LOG.info("=== ORACLE SPOUT CONFIGURATION ===");
        LOG.info("  Component ID: {}", ctx.getThisComponentId());
        LOG.info("  Task ID: {}", ctx.getThisTaskId());
        LOG.info("  Worker Port: {}", ctx.getThisWorkerPort());
        LOG.info("  jdbc.url: {}", jdbcUrl);
        LOG.info("  jdbc.user: {}", user);
        LOG.info("  jdbc.pass: {}", pass != null ? "***CONFIGURED***" : "NULL");
        
        if (jdbcUrl == null || user == null || pass == null) {
            LOG.error("=== CRITICAL ERROR: JDBC CONFIGURATION MISSING ===");
            if (jdbcUrl == null) LOG.error("  jdbc.url is not set");
            if (user == null) LOG.error("  jdbc.user is not set");
            if (pass == null) LOG.error("  jdbc.pass is not set");
        } else {
            LOG.info("=== ORACLE SPOUT CONFIGURATION COMPLETE ===");
            initializeConnection();
        }
        
        LOG.info("============= SIMPLE ORACLE SPOUT OPENED =============");
    }

    private void initializeConnection() {
        LOG.info("=== INITIALIZING DATABASE CONNECTION ===");
        int maxRetries = 10;
        int retryDelay = 5000; // 5 seconds
        
        for (int attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                LOG.info("Loading Oracle JDBC driver (attempt {})...", attempt);
                Class.forName("oracle.jdbc.OracleDriver");
                LOG.info("✓ Oracle JDBC driver loaded successfully (attempt {})", attempt);
                
                try {
                    if (connection != null && !connection.isClosed()) {
                        connection.close();
                    }
                    
                    LOG.info("Attempting database connection to: {}", jdbcUrl);
                    connection = DriverManager.getConnection(jdbcUrl, user, pass);
                    connection.setAutoCommit(true);
                    
                    LOG.info("✓ Database connection established successfully on attempt {}", attempt);
                    testDatabaseConnection();
                    connectionInitialized = true;
                    return;
                } catch (SQLException e) {
                    LOG.error("✗ Failed to establish database connection on attempt {}: {}", 
                             attempt, e.getMessage());
                    LOG.error("SQL Error Code: {}, SQL State: {}", e.getErrorCode(), e.getSQLState());
                }
            } catch (ClassNotFoundException e) {
                LOG.error("✗ Oracle JDBC driver not found on attempt {}: {}", 
                         attempt, e.getMessage());
                LOG.error("Classpath: {}", System.getProperty("java.class.path"));
            } catch (Exception e) {
                LOG.error("✗ Unexpected error on attempt {}: {}", 
                         attempt, e.getMessage(), e);
            }
            
            if (attempt < maxRetries) {
                LOG.info("Retrying in {} seconds...", retryDelay / 1000);
                try {
                    Thread.sleep(retryDelay);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }
        }
        LOG.error("✗ All database connection attempts failed after {} retries", maxRetries);
    }

    private void testDatabaseConnection() {
        LOG.info("=== TESTING DATABASE CONNECTION ===");
        
        try {
            try (PreparedStatement ps = connection.prepareStatement("SELECT COUNT(*) FROM crawl_queue")) {
                try (ResultSet rs = ps.executeQuery()) {
                    if (rs.next()) {
                        int total = rs.getInt(1);
                        LOG.info("Total URLs in table: {}", total);
                    }
                }
            }
            
            try (PreparedStatement ps = connection.prepareStatement("SELECT status, COUNT(*) FROM crawl_queue GROUP BY status")) {
                try (ResultSet rs = ps.executeQuery()) {
                    LOG.info("Status breakdown:");
                    while (rs.next()) {
                        String status = rs.getString(1);
                        int count = rs.getInt(2);
                        LOG.info("  {}: {}", status, count);
                    }
                }
            }
            
            LOG.info("✓ Database connection test SUCCESSFUL");
        } catch (SQLException e) {
            LOG.error("✗ Database test failed: {}", e.getMessage(), e);
        }
    }

    @Override
    public void nextTuple() {
        long currentTime = System.currentTimeMillis();
        if (currentTime - lastLogTime > 30000) {
            LOG.info("=== SPOUT STATISTICS ===");
            LOG.info("Total URLs fetched from DB: {}", totalFetched);
            LOG.info("Total URLs emitted: {}", totalEmitted);
            LOG.info("Queue size: {}", queue.size());
            LOG.info("Pending acks: {}", pending.size());
            LOG.info("Connection initialized: {}", connectionInitialized);
            lastLogTime = currentTime;
        }
        
        if (!connectionInitialized) {
            LOG.warn("Database connection not initialized, attempting to reconnect...");
            initializeConnection();
            if (!connectionInitialized) {
                LOG.warn("Still no connection, sleeping 5 seconds...");
                sleep(5000);
                return;
            }
        }

        if (queue.size() < minQueueRefillThreshold &&
                (System.currentTimeMillis() - lastFetchTime) > fetchIntervalMs) {
            fetchUrlsFromDb();
            lastFetchTime = System.currentTimeMillis();
        }

        String url = queue.poll();
        if (url != null) {
            Metadata metadata = new Metadata();
            Object msgId = url + "_" + System.nanoTime();
            pending.put(msgId, url);
            LOG.debug("Emitting URL {}", url);
            collector.emit(new Values(url, metadata), msgId);
            totalEmitted++;
        } else {
            sleep(100);
        }
    }

    @Override
    public void ack(Object msgId) {
        String url = pending.remove(msgId);
        LOG.info("✓ ACK for msgId: {} (URL: {})", msgId, url);
        if (url != null) {
            updateUrlStatus(url, "FETCHED");
        }
    }

    @Override
    public void fail(Object msgId) {
        String url = pending.remove(msgId);
        LOG.warn("✗ FAIL for msgId: {} (URL: {})", msgId, url);
        if (url != null) {
            updateUrlStatus(url, "ERROR");
        }
    }

    private void fetchUrlsFromDb() {
        final String selectSQL =
                "SELECT url FROM " + statusTableName() +
                " WHERE status IN ('NEW','DISCOVERED') " +
                " AND (nextfetchdate IS NULL OR nextfetchdate <= SYSTIMESTAMP) " +
                " AND ROWNUM <= ? " +
                (useRowLocking ? " FOR UPDATE SKIP LOCKED" : "");
        LOG.debug("Selecting up to {} URLs (locking={})", fetchBatchSize, useRowLocking);
        try {
            if (connection == null || connection.isClosed()) {
                initializeConnection();
                if (!connectionInitialized) return;
            }
            if (useRowLocking) connection.setAutoCommit(false);
            int selected = 0;
            try (PreparedStatement ps = connection.prepareStatement(selectSQL)) {
                ps.setInt(1, fetchBatchSize);
                try (ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        String u = rs.getString(1);
                        if (u != null && !u.isBlank()) {
                            queue.offer(u);
                            selected++;
                        }
                    }
                }
            }
            if (selected > 0 && useRowLocking) {
                try (PreparedStatement ups = connection.prepareStatement(
                        "UPDATE " + statusTableName() +
                        " SET status='FETCHING', last_updated = SYSTIMESTAMP " +
                        " WHERE url IN (SELECT url FROM " + statusTableName() +
                        " WHERE status='FETCHING' OR status='NEW' OR status='DISCOVERED') AND ROWNUM <= ?")) {
                    ups.setInt(1, selected);
                    ups.executeUpdate();
                } catch (SQLException ignore) {}
            }
            if (useRowLocking) connection.commit();
            totalFetched += selected;
            LOG.info("Fetched {} URLs (queueSize={}, totalFetched={})", selected, queue.size(), totalFetched);
        } catch (SQLException e) {
            LOG.error("DB fetch failure: {}", e.getMessage(), e);
            try { if (useRowLocking && connection != null) connection.rollback(); } catch (SQLException ignore) {}
            connectionInitialized = false;
        } finally {
            if (useRowLocking) {
                try { connection.setAutoCommit(true); } catch (SQLException ignore) {}
            }
        }
    }

    private void updateUrlStatus(String url, String status) {
        final String sql =
            "UPDATE " + statusTableName() +
            " SET status = ?, nextfetchdate = (CASE WHEN ?='FETCHED' THEN SYSTIMESTAMP + (1/24/12) ELSE nextfetchdate END) " +
            " WHERE url = ?";
        
        LOG.debug("Updating status {} -> {}", url, status);
        
        try {
            if (connection == null || connection.isClosed()) {
                initializeConnection();
                if (!connectionInitialized) {
                    LOG.error("Failed to update status for URL: {} to {}", url, status);
                    return;
                }
            }
            
            try (PreparedStatement ps = connection.prepareStatement(sql)) {
                ps.setString(1, status);
                ps.setString(2, status);
                ps.setString(3, url);
                int updated = ps.executeUpdate();
                LOG.debug("Updated {} rows to {} for URL: {}", updated, status, url);
            }
        } catch (SQLException e) {
            LOG.error("Database error updating status to {}: {}", status, e.getMessage(), e);
            connectionInitialized = false;
        }
    }

    private String statusTableName(){
        return "crawl_queue";
    }

    // Helpers
    private static String asString(Object o) {
        if (o == null) return null;
        String s = o.toString().trim();
        return s.isEmpty() ? null : s;
    }
    private static String firstNonEmpty(String... vals){
        for (String v: vals) if (v!=null && !v.trim().isEmpty()) return v;
        return null;
    }
    private static int parseIntOrDefault(Object confVal, String envVal, int def){
        try {
            if (confVal != null) return Integer.parseInt(confVal.toString());
            if (envVal != null && !envVal.isBlank()) return Integer.parseInt(envVal);
        } catch (NumberFormatException ignore){}
        return def;
    }
    private void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    @Override
    public void declareOutputFields(OutputFieldsDeclarer declarer) {
        LOG.info("Declaring output fields: url, metadata");
        declarer.declare(new Fields("url", "metadata"));
    }
    
    @Override
    public void close() {
        LOG.info("Closing SimpleOracleSpout...");
        try {
            if (connection != null && !connection.isClosed()) {
                connection.close();
                LOG.info("✓ Database connection closed successfully");
            }
        } catch (SQLException e) {
            LOG.error("✗ Error closing database connection: {}", e.getMessage());
        }
        LOG.info("SimpleOracleSpout closed");
    }
}
