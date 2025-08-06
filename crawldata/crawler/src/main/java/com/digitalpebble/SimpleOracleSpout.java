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
        
        // Get configuration from Storm config or use hardcoded values
        this.jdbcUrl = (String) conf.getOrDefault("sql.connection.string", "jdbc:oracle:thin:@//oracle-test:1521/XE");
        this.user = (String) conf.getOrDefault("sql.user", "c##mojtaba");
        this.pass = (String) conf.getOrDefault("sql.password", "bjnSY55l0g1IrzWY71Jg");
        
        LOG.info("=== ORACLE SPOUT CONFIGURATION ===");
        LOG.info("  Component ID: {}", ctx.getThisComponentId());
        LOG.info("  Task ID: {}", ctx.getThisTaskId());
        LOG.info("  Worker Port: {}", ctx.getThisWorkerPort());
        LOG.info("  jdbc.url: {}", jdbcUrl);
        LOG.info("  jdbc.user: {}", user);
        LOG.info("  jdbc.pass: {}", pass != null ? "***CONFIGURED***" : "NULL");
        
        if (jdbcUrl == null || user == null || pass == null) {
            LOG.error("=== CRITICAL ERROR: JDBC CONFIGURATION MISSING ===");
            LOG.error("Missing configuration keys:");
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
                    return; // Success, exit retry loop
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
            // Check total count
            try (PreparedStatement ps = connection.prepareStatement("SELECT COUNT(*) FROM crawl_queue")) {
                try (ResultSet rs = ps.executeQuery()) {
                    if (rs.next()) {
                        int total = rs.getInt(1);
                        LOG.info("Total URLs in table: {}", total);
                    }
                }
            }
            
            // Check status breakdown
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
        // Log periodic statistics
        long currentTime = System.currentTimeMillis();
        if (currentTime - lastLogTime > 30000) { // Every 30 seconds
            LOG.info("=== SPOUT STATISTICS ===");
            LOG.info("Total URLs fetched from DB: {}", totalFetched);
            LOG.info("Total URLs emitted: {}", totalEmitted);
            LOG.info("Queue size: {}", queue.size());
            LOG.info("Pending acks: {}", pending.size());
            LOG.info("Connection initialized: {}", connectionInitialized);
            lastLogTime = currentTime;
        }
        
        // Ensure we have a valid connection before proceeding
        if (!connectionInitialized) {
            LOG.warn("Database connection not initialized, attempting to reconnect...");
            initializeConnection();
            if (!connectionInitialized) {
                LOG.warn("Still no connection, sleeping 5 seconds...");
                sleep(5000);
                return;
            }
        }

        // Fetch more URLs if queue is low and enough time has passed
        if (queue.size() < 10 && (currentTime - lastFetchTime) > FETCH_INTERVAL_MS) {
            LOG.debug("Queue is low ({} items), fetching URLs from database...", queue.size());
            fetchUrlsFromDb();
            lastFetchTime = currentTime;
        }

        String url = queue.poll();
        if (url != null) {
            // Create proper metadata for StormCrawler
            Metadata metadata = new Metadata();
            
            // Use URL as message ID for tracking
            Object msgId = url + "_" + System.currentTimeMillis();
            pending.put(msgId, url);
            
            LOG.info("✓ EMITTING URL: {} with msgId: {}", url, msgId);
            collector.emit(new Values(url, metadata), msgId);
            totalEmitted++;
        } else {
            LOG.trace("No URL to emit, sleeping 100ms...");
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
        final String sql = "SELECT url FROM crawl_queue WHERE status='NEW' AND ROWNUM <= ?";
        
        LOG.debug("Executing SQL: {} with batch size: {}", sql, FETCH_BATCH_SIZE);
        
        try {
            if (connection == null || connection.isClosed()) {
                LOG.warn("Connection closed or null, reconnecting...");
                initializeConnection();
                if (!connectionInitialized) {
                    return;
                }
            }
            
            try (PreparedStatement ps = connection.prepareStatement(sql)) {
                ps.setInt(1, FETCH_BATCH_SIZE);
                ps.setQueryTimeout(30);

                try (ResultSet rs = ps.executeQuery()) {
                    int count = 0;
                    while (rs.next()) {
                        String url = rs.getString("url");
                        if (url != null && !url.trim().isEmpty()) {
                            queue.offer(url);
                            count++;
                            LOG.debug("Queued URL: {}", url);
                        }
                    }
                    
                    totalFetched += count;
                    if (count > 0) {
                        LOG.info("✓ Fetched {} URLs from database (total fetched: {})", count, totalFetched);
                    } else {
                        LOG.info("No NEW URLs found in database");
                    }
                }
            }
        } catch (SQLException e) {
            LOG.error("Database error while fetching URLs: {}", e.getMessage(), e);
            connectionInitialized = false;
        } catch (Exception e) {
            LOG.error("Unexpected error while fetching URLs: {}", e.getMessage(), e);
            connectionInitialized = false;
        }
    }

    private void updateUrlStatus(String url, String status) {
        final String sql = "UPDATE crawl_queue SET status = ? WHERE url = ?";
        
        LOG.debug("Updating status for URL {} to {}", url, status);
        
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
                ps.setString(2, url);
                int updated = ps.executeUpdate();
                LOG.debug("Updated {} rows to {} for URL: {}", updated, status, url);
            }
        } catch (SQLException e) {
            LOG.error("Database error updating status to {}: {}", status, e.getMessage(), e);
            connectionInitialized = false;
        }
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