package com.example.crawler;

import org.apache.storm.Config;
import org.apache.storm.LocalCluster;
import org.apache.storm.StormSubmitter;
import org.apache.storm.generated.AlreadyAliveException;
import org.apache.storm.generated.AuthorizationException;
import org.apache.storm.generated.InvalidTopologyException;
import org.apache.storm.topology.TopologyBuilder;
import org.apache.storm.tuple.Fields;

import com.digitalpebble.stormcrawler.ConfigurableTopology;
import com.digitalpebble.stormcrawler.Constants;
import com.digitalpebble.stormcrawler.bolt.FetcherBolt;
import com.digitalpebble.stormcrawler.bolt.JSoupParserBolt;
import com.digitalpebble.stormcrawler.bolt.SiteMapParserBolt;
import com.digitalpebble.stormcrawler.bolt.URLPartitionerBolt;
import com.digitalpebble.stormcrawler.elasticsearch.bolt.DeletionBolt;
import com.digitalpebble.stormcrawler.elasticsearch.bolt.IndexerBolt;
import com.digitalpebble.stormcrawler.elasticsearch.persistence.StatusUpdaterBolt;
import com.digitalpebble.stormcrawler.spout.FileSpout;

public class CrawlTopology extends ConfigurableTopology {

    public static void main(String[] args) throws Exception {
        ConfigurableTopology.start(new CrawlTopology(), args);
    }

    @Override
    protected int run(String[] args) {
        TopologyBuilder builder = new TopologyBuilder();

        // 1. Spout: seeds
        builder.setSpout("spout", new FileSpout(), 1);

        // 2. Partition URLs by host/domain
        builder.setBolt("partitioner", new URLPartitionerBolt(), 1)
               .shuffleGrouping("spout");

        // 3. Fetch HTML and XML
        builder.setBolt("fetcher", new FetcherBolt(), 5)
               .fieldsGrouping("partitioner", new Fields("key"));

        // 4a. Sitemap parsing
        builder.setBolt("sitemap", new SiteMapParserBolt(), 1)
               .localOrShuffleGrouping("fetcher");

        // 4b. HTML parsing (both sitemaps + normal)
        builder.setBolt("parser", new JSoupParserBolt(), 2)
               .localOrShuffleGrouping("sitemap")
               .localOrShuffleGrouping("fetcher");

        // 5. Index content
        builder.setBolt("indexer", new IndexerBolt(), 1)
               .localOrShuffleGrouping("parser");

        // 6. Update status in ES
        builder.setBolt("status", new StatusUpdaterBolt(), 1)
               .localOrShuffleGrouping("fetcher", Constants.StatusStreamName)
               .localOrShuffleGrouping("sitemap", Constants.StatusStreamName)
               .localOrShuffleGrouping("parser", Constants.StatusStreamName)
               .localOrShuffleGrouping("indexer", Constants.StatusStreamName);

        // 7. Deletions
        builder.setBolt("deletion", new DeletionBolt(), 1)
               .localOrShuffleGrouping("status", Constants.DELETION_STREAM_NAME);

        Config config = new Config();
        config.setDebug(false);

        String topologyName = "crawl";
        if (args.length == 0) {
            config.setMaxTaskParallelism(10);
            try {
                LocalCluster cluster = new LocalCluster();
                cluster.submitTopology(topologyName, config, builder.createTopology());
            } catch (Exception e) {
                throw new RuntimeException("Failed to submit topology locally", e);
            }
        } else {
            config.setNumWorkers(4);
            try {
                StormSubmitter.submitTopology(topologyName, config, builder.createTopology());
            } catch (Exception e) {
                throw new RuntimeException("Failed to submit topology", e);
            }
        }
        return 0;
    }
}