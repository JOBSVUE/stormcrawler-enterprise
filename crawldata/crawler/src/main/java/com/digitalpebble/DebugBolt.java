package com.digitalpebble;

import java.util.Map;

import org.apache.storm.task.OutputCollector;
import org.apache.storm.task.TopologyContext;
import org.apache.storm.topology.OutputFieldsDeclarer;
import org.apache.storm.topology.base.BaseRichBolt;
import org.apache.storm.tuple.Tuple;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.digitalpebble.stormcrawler.Metadata;

/**
 * Simple debug bolt that logs all tuples it receives
 */
public class DebugBolt extends BaseRichBolt {
    private static final Logger LOG = LoggerFactory.getLogger(DebugBolt.class);
    private OutputCollector collector;
    private long count = 0;
    private long lastLogTime = 0;
    private static final long LOG_INTERVAL_MS = 10000; // Log every 10 seconds

    @Override
    public void prepare(Map<String, Object> conf, TopologyContext context, OutputCollector collector) {
        this.collector = collector;
        LOG.info("==== DEBUG BOLT INITIALIZED ====");
        LOG.info("Component ID: {}", context.getThisComponentId());
        LOG.info("Task ID: {}", context.getThisTaskId());
    }

    @Override
    public void execute(Tuple tuple) {
        count++;
        long now = System.currentTimeMillis();
        
        // Process the tuple based on its structure
        String url = tuple.getStringByField("url");
        Metadata metadata = (Metadata) tuple.getValueByField("metadata");
        
        // Detailed logging but not too frequent to avoid log flooding
        if (count % 10 == 0 || now - lastLogTime > LOG_INTERVAL_MS) {
            LOG.info("==== DEBUG BOLT RECEIVED TUPLE #{} ====", count);
            LOG.info("URL: {}", url);
            LOG.info("Metadata: {}", metadata);
            lastLogTime = now;
        }
        
        // Always ack the tuple
        collector.ack(tuple);
    }

    @Override
    public void declareOutputFields(OutputFieldsDeclarer declarer) {
        // No output fields as this is just a debug bolt
    }
    
    @Override
    public void cleanup() {
        LOG.info("==== DEBUG BOLT CLEANUP ====");
        LOG.info("Total tuples processed: {}", count);
    }
}