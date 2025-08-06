package com.digitalpebble;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.util.Map;

import org.apache.storm.task.OutputCollector;
import org.apache.storm.task.TopologyContext;
import org.apache.storm.topology.OutputFieldsDeclarer;
import org.apache.storm.topology.base.BaseRichBolt;
import org.apache.storm.tuple.Tuple;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.digitalpebble.stormcrawler.persistence.Status;

/**
 * SQL implementation of the status updater bolt. Updates the status of URLs in
 * an SQL database.
 */
public class SQLStatusUpdaterBolt extends BaseRichBolt {
    private static final Logger LOG = LoggerFactory.getLogger(SQLStatusUpdaterBolt.class);

    private OutputCollector collector;
    private Connection connection;
    private String connectionString;
    private String username;
    private String password;
    private String statusTable;
    private boolean showSQL = false;
    private int maxRetries = 3;
    private long retryIntervalMs = 2000;

    @Override
    public void prepare(Map<String, Object> conf, TopologyContext context, OutputCollector collector) {
        this.collector = collector;
        
        // Get configuration values
        connectionString = (String) conf.get("sql.connection.string");
        username = (String) conf.get("sql.user");
        password = (String) conf.get("sql.password");
        statusTable = (String) conf.get("sql.status.table");
        
        if (conf.containsKey("sql.show.sql")) {
            showSQL = Boolean.parseBoolean(String.valueOf(conf.get("sql.show.sql")));
        }
        
        if (conf.containsKey("sql.max.retries")) {
            maxRetries = Integer.parseInt(String.valueOf(conf.get("sql.max.retries")));
        }
        
        if (conf.containsKey("sql.retry.interval.ms")) {
            retryIntervalMs = Long.parseLong(String.valueOf(conf.get("sql.retry.interval.ms")));
        }
        
        LOG.info("=== SQL STATUS UPDATER CONFIGURATION ===");
        LOG.info("Connection String: {}", connectionString);
        LOG.info("Username: {}", username);
        LOG.info("Status Table: {}", statusTable);
        LOG.info("Show SQL: {}", showSQL);
        LOG.info("Max Retries: {}", maxRetries);
        LOG.info("Retry Interval: {} ms", retryIntervalMs);
        
        initializeConnection();
    }

    private void initializeConnection() {
        LOG.info("Initializing SQL connection...");
        int attempts = 0;
        boolean connected = false;
        
        while (!connected && attempts < maxRetries) {
            attempts++;
            try {
                // Load the JDBC driver
                Class.forName("oracle.jdbc.OracleDriver");
                LOG.info("Oracle JDBC driver loaded successfully");
                
                // Establish connection
                connection = DriverManager.getConnection(connectionString, username, password);
                connection.setAutoCommit(true);
                connected = true;
                LOG.info("Successfully connected to the database on attempt {}", attempts);
            } catch (ClassNotFoundException e) {
                LOG.error("Oracle JDBC driver not found: {}", e.getMessage(), e);
            } catch (SQLException e) {
                LOG.error("SQL error connecting to database on attempt {}: {}", attempts, e.getMessage());
                if (attempts < maxRetries) {
                    LOG.info("Retrying in {} ms...", retryIntervalMs);
                    try {
                        Thread.sleep(retryIntervalMs);
                    } catch (InterruptedException ie) {
                        Thread.currentThread().interrupt();
                    }
                }
            }
        }
        
        if (!connected) {
            LOG.error("Failed to connect to database after {} attempts", maxRetries);
        }
    }
    
    @Override
    public void execute(Tuple tuple) {
        String url = tuple.getStringByField("url");
        Status status = (Status) tuple.getValueByField("status");
        
        // Map StormCrawler status to database status
        String statusString = mapStatusToDb(status);
        LOG.info("Updating status for URL: {} to {} (StormCrawler: {})", url, statusString, status);
        
        if (connection == null) {
            LOG.warn("Database connection is null, reconnecting...");
            initializeConnection();
            if (connection == null) {
                LOG.error("Failed to reconnect to database, cannot update status");
                collector.fail(tuple);
                return;
            }
        }
        
        // Use MERGE statement for upsert functionality
        final String sql = "MERGE INTO " + statusTable + " t USING (SELECT ? as url, ? as status FROM dual) s " +
                          "ON (t.url = s.url) " +
                          "WHEN MATCHED THEN UPDATE SET t.status = s.status, t.nextfetchdate = SYSTIMESTAMP " +
                          "WHEN NOT MATCHED THEN INSERT (url, status, nextfetchdate, host) " +
                          "VALUES (s.url, s.status, SYSTIMESTAMP, ?)";
        
        if (showSQL) {
            LOG.info("SQL: {} with params [{}, {}, {}]", sql, url, statusString, extractHost(url));
        }
        
        try {
            try (PreparedStatement statement = connection.prepareStatement(sql)) {
                statement.setString(1, url);
                statement.setString(2, statusString);
                statement.setString(3, extractHost(url));
                int updated = statement.executeUpdate();
                
                LOG.debug("Processed {} rows for URL: {}", updated, url);
                collector.ack(tuple);
            }
        } catch (SQLException e) {
            LOG.error("Error updating status for URL {}: {}", url, e.getMessage(), e);
            try {
                if (connection.isClosed()) {
                    LOG.warn("Connection closed, reconnecting...");
                    initializeConnection();
                }
            } catch (SQLException reconnectError) {
                LOG.error("Error checking connection: {}", reconnectError.getMessage());
            }
            collector.fail(tuple);
        }
    }
    
    private String mapStatusToDb(Status status) {
        switch (status) {
            case DISCOVERED:
                return "NEW";
            case FETCHED:
                return "FETCHED";
            case ERROR:
                return "ERROR";
            case REDIRECTION:
                return "REDIRECT";
            default:
                return status.toString();
        }
    }
    
    private String extractHost(String url) {
        try {
            java.net.URL u = new java.net.URL(url);
            return u.getHost();
        } catch (Exception e) {
            LOG.warn("Failed to extract host from URL: {}", url);
            return "unknown";
        }
    }

    @Override
    public void cleanup() {
        if (connection != null) {
            try {
                connection.close();
                LOG.info("Database connection closed");
            } catch (SQLException e) {
                LOG.error("Error closing database connection: {}", e.getMessage());
            }
        }
    }

    @Override
    public void declareOutputFields(OutputFieldsDeclarer declarer) {
        // No output fields to declare as this is a terminal bolt
    }
}
