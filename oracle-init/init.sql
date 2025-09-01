-- Simple initialization script for testing JDBCSpout + SQLStatusUpdaterBolt

-- 1) Create user/schema
CREATE USER c##mojtaba IDENTIFIED BY bjnSY55l0g1IrzWY71Jg QUOTA UNLIMITED ON USERS;
GRANT CONNECT, RESOURCE TO c##mojtaba;

-- 2) Connect as the new user
CONNECT c##mojtaba/bjnSY55l0g1IrzWY71Jg;

-- 3) Create the queue table with a schema compatible with StormCrawler's default SQLStatusUpdaterBolt
CREATE TABLE crawl_queue (
  url           VARCHAR2(1000) PRIMARY KEY,
  status        VARCHAR2(20)    DEFAULT 'NEW',
  nextfetchdate TIMESTAMP       DEFAULT SYSTIMESTAMP,
  metadata      CLOB,
  bucket        INTEGER         DEFAULT 0,
  host          VARCHAR2(250),
  depth         INTEGER         DEFAULT 0
);

-- Create indexes for better performance
CREATE INDEX idx_crawl_queue_status ON crawl_queue(status);
CREATE INDEX idx_crawl_queue_host ON crawl_queue(host);
CREATE INDEX idx_crawl_queue_nextfetch ON crawl_queue(nextfetchdate);
CREATE INDEX idx_crawl_queue_depth ON crawl_queue(depth);


-- Fortune 100 Companies - Seed URLs for StormCrawler
-- filepath: /home/mojtaba/archive/stormcrawler-enterprise-archive/fortune100_seeds.sql

-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.walmart.com/', 'NEW', SYSTIMESTAMP, 'www.walmart.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.amazon.com/', 'NEW', SYSTIMESTAMP, 'www.amazon.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.exxonmobil.com/', 'NEW', SYSTIMESTAMP, 'www.exxonmobil.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.apple.com/', 'NEW', SYSTIMESTAMP, 'www.apple.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.unitedhealth.com/', 'NEW', SYSTIMESTAMP, 'www.unitedhealth.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.berkshirehathaway.com/', 'NEW', SYSTIMESTAMP, 'www.berkshirehathaway.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.alphabet.com/', 'NEW', SYSTIMESTAMP, 'www.alphabet.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.mckesson.com/', 'NEW', SYSTIMESTAMP, 'www.mckesson.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.amerisourcebergen.com/', 'NEW', SYSTIMESTAMP, 'www.amerisourcebergen.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.microsoft.com/', 'NEW', SYSTIMESTAMP, 'www.microsoft.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.chevron.com/', 'NEW', SYSTIMESTAMP, 'www.chevron.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.costco.com/', 'NEW', SYSTIMESTAMP, 'www.costco.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.cardinalhealth.com/', 'NEW', SYSTIMESTAMP, 'www.cardinalhealth.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.cvshealth.com/', 'NEW', SYSTIMESTAMP, 'www.cvshealth.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.att.com/', 'NEW', SYSTIMESTAMP, 'www.att.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.generalelectric.com/', 'NEW', SYSTIMESTAMP, 'www.ge.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.ford.com/', 'NEW', SYSTIMESTAMP, 'www.ford.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.fanniemae.com/', 'NEW', SYSTIMESTAMP, 'www.fanniemae.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.homedepot.com/', 'NEW', SYSTIMESTAMP, 'www.homedepot.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.meta.com/', 'NEW', SYSTIMESTAMP, 'www.meta.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.verizon.com/', 'NEW', SYSTIMESTAMP, 'www.verizon.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.kroger.com/', 'NEW', SYSTIMESTAMP, 'www.kroger.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.walgreens.com/', 'NEW', SYSTIMESTAMP, 'www.walgreens.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.jpmorgan.com/', 'NEW', SYSTIMESTAMP, 'www.jpmorgan.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.tesla.com/', 'NEW', SYSTIMESTAMP, 'www.tesla.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.marathon.com/', 'NEW', SYSTIMESTAMP, 'www.marathonpetroleum.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.phillips66.com/', 'NEW', SYSTIMESTAMP, 'www.phillips66.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.generalmotors.com/', 'NEW', SYSTIMESTAMP, 'www.gm.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.elevancehealth.com/', 'NEW', SYSTIMESTAMP, 'www.elevancehealth.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.valero.com/', 'NEW', SYSTIMESTAMP, 'www.valero.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.bankofamerica.com/', 'NEW', SYSTIMESTAMP, 'www.bankofamerica.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.wellsfargo.com/', 'NEW', SYSTIMESTAMP, 'www.wellsfargo.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.target.com/', 'NEW', SYSTIMESTAMP, 'www.target.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.deltaair.com/', 'NEW', SYSTIMESTAMP, 'www.delta.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.lowes.com/', 'NEW', SYSTIMESTAMP, 'www.lowes.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.citigroup.com/', 'NEW', SYSTIMESTAMP, 'www.citigroup.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.comcastcorporation.com/', 'NEW', SYSTIMESTAMP, 'www.comcastcorporation.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.humana.com/', 'NEW', SYSTIMESTAMP, 'www.humana.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.starbucks.com/', 'NEW', SYSTIMESTAMP, 'www.starbucks.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.centene.com/', 'NEW', SYSTIMESTAMP, 'www.centene.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.ibm.com/', 'NEW', SYSTIMESTAMP, 'www.ibm.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.fedex.com/', 'NEW', SYSTIMESTAMP, 'www.fedex.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.americanexpress.com/', 'NEW', SYSTIMESTAMP, 'www.americanexpress.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.energy-transfer.com/', 'NEW', SYSTIMESTAMP, 'www.energytransfer.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.ups.com/', 'NEW', SYSTIMESTAMP, 'www.ups.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.albertsons.com/', 'NEW', SYSTIMESTAMP, 'www.albertsonscompanies.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.sysco.com/', 'NEW', SYSTIMESTAMP, 'www.sysco.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.nike.com/', 'NEW', SYSTIMESTAMP, 'www.nike.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.boeing.com/', 'NEW', SYSTIMESTAMP, 'www.boeing.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.johnsoncontrols.com/', 'NEW', SYSTIMESTAMP, 'www.johnsoncontrols.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.aig.com/', 'NEW', SYSTIMESTAMP, 'www.aig.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.netflix.com/', 'NEW', SYSTIMESTAMP, 'www.netflix.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.intel.com/', 'NEW', SYSTIMESTAMP, 'www.intel.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.oracle.com/', 'NEW', SYSTIMESTAMP, 'www.oracle.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.cisco.com/', 'NEW', SYSTIMESTAMP, 'www.cisco.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.prudential.com/', 'NEW', SYSTIMESTAMP, 'www.prudential.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.tiaa.org/', 'NEW', SYSTIMESTAMP, 'www.tiaa.org', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.thehartford.com/', 'NEW', SYSTIMESTAMP, 'www.thehartford.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.pepsico.com/', 'NEW', SYSTIMESTAMP, 'www.pepsico.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.coca-colacompany.com/', 'NEW', SYSTIMESTAMP, 'www.coca-colacompany.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.pfizer.com/', 'NEW', SYSTIMESTAMP, 'www.pfizer.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.abbvie.com/', 'NEW', SYSTIMESTAMP, 'www.abbvie.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.merck.com/', 'NEW', SYSTIMESTAMP, 'www.merck.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.jnj.com/', 'NEW', SYSTIMESTAMP, 'www.jnj.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.dell.com/', 'NEW', SYSTIMESTAMP, 'www.dell.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.hp.com/', 'NEW', SYSTIMESTAMP, 'www.hp.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.goldmansachs.com/', 'NEW', SYSTIMESTAMP, 'www.goldmansachs.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.morganstanley.com/', 'NEW', SYSTIMESTAMP, 'www.morganstanley.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.lockheedmartin.com/', 'NEW', SYSTIMESTAMP, 'www.lockheedmartin.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.aetna.com/', 'NEW', SYSTIMESTAMP, 'www.aetna.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.caterpillar.com/', 'NEW', SYSTIMESTAMP, 'www.caterpillar.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.deere.com/', 'NEW', SYSTIMESTAMP, 'www.deere.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.3m.com/', 'NEW', SYSTIMESTAMP, 'www.3m.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.honeywell.com/', 'NEW', SYSTIMESTAMP, 'www.honeywell.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.dow.com/', 'NEW', SYSTIMESTAMP, 'www.dow.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.dupont.com/', 'NEW', SYSTIMESTAMP, 'www.dupont.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.conocophillips.com/', 'NEW', SYSTIMESTAMP, 'www.conocophillips.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.kimberly-clark.com/', 'NEW', SYSTIMESTAMP, 'www.kimberly-clark.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.pg.com/', 'NEW', SYSTIMESTAMP, 'www.pg.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.colgatepalmolive.com/', 'NEW', SYSTIMESTAMP, 'www.colgatepalmolive.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.generaldynamics.com/', 'NEW', SYSTIMESTAMP, 'www.generaldynamics.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.raytheon.com/', 'NEW', SYSTIMESTAMP, 'www.rtx.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.northropgrumman.com/', 'NEW', SYSTIMESTAMP, 'www.northropgrumman.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.disney.com/', 'NEW', SYSTIMESTAMP, 'www.thewaltdisneycompany.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.warnerbros.com/', 'NEW', SYSTIMESTAMP, 'www.wbd.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.mcdonalds.com/', 'NEW', SYSTIMESTAMP, 'www.mcdonalds.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yum.com/', 'NEW', SYSTIMESTAMP, 'www.yum.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.marriott.com/', 'NEW', SYSTIMESTAMP, 'www.marriott.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.hilton.com/', 'NEW', SYSTIMESTAMP, 'www.hilton.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.southwest.com/', 'NEW', SYSTIMESTAMP, 'www.southwest.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.united.com/', 'NEW', SYSTIMESTAMP, 'www.united.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.americanairlines.com/', 'NEW', SYSTIMESTAMP, 'www.aa.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.jetblue.com/', 'NEW', SYSTIMESTAMP, 'www.jetblue.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.amd.com/', 'NEW', SYSTIMESTAMP, 'www.amd.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.nvidia.com/', 'NEW', SYSTIMESTAMP, 'www.nvidia.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.qualcomm.com/', 'NEW', SYSTIMESTAMP, 'www.qualcomm.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.broadcom.com/', 'NEW', SYSTIMESTAMP, 'www.broadcom.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.salesforce.com/', 'NEW', SYSTIMESTAMP, 'www.salesforce.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.servicenow.com/', 'NEW', SYSTIMESTAMP, 'www.servicenow.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.workday.com/', 'NEW', SYSTIMESTAMP, 'www.workday.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.adobe.com/', 'NEW', SYSTIMESTAMP, 'www.adobe.com', 0);
-- 4) Seed the table with test URLs using NEW status
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('http://books.toscrape.com/', 'NEW', SYSTIMESTAMP, 'books.toscrape.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://yjc.ir/en', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/religion', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://ai-ark.com/', 'NEW', SYSTIMESTAMP, 'ai-ark.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('http://apollo.io/', 'NEW', SYSTIMESTAMP, 'apollo.io', 0);
--INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://orq.ai/', 'NEW', SYSTIMESTAMP, 'orq.ai', 0);
--INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/51053/iran-calls-for-muslim-unity-against-west%E2%80%99s-islamophobia-campaign', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/54036/pompeo-being-tougher-on-iran-is-biden%E2%80%99s-key-to-saudi-arabia-israel-normalization', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/54014/texas-constable-deputy-fatally-shot', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/56157/deep-pocket-who-were-on-epsteins-pocket-list', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/55906/no-united-states-equals-peace', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/55383/he-is-bad-news', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/55351/sanders-us-is-not-able-to-afford-its-basic-medical-needs', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/55350/the-rise-of-islamophobia', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/55275/the-united-states-captures-saddam-hussein-former-leader-of-iraq', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/55260/zionists-in-charge', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/55198/the-truth-behind-mbs-relation-with-the-us', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/55172/firearms-in-the-us-statistics-and-facts', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://news.cgtn.com/news/2025-08-08/Modi-pledges-support-for-farmers-amid-Trump-s-tariff-threat--1FFCeheM8KY/p.html', 'NEW', SYSTIMESTAMP, 'cgtn.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/54690/malcolm-x%E2%80%99s-daughter-malikah-shabazz-found-dead-in-nyc-home', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.yjc.ir/en/news/51305/stop-lying-muslim-advocacy-group-sues-facebook-over-claims-it-removes-hate-speech-hate-speech', 'NEW', SYSTIMESTAMP, 'yjc.ir', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://test-fetched.com', 'FETCHED', SYSTIMESTAMP, 'test-fetched.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://test-error.com', 'ERROR', SYSTIMESTAMP, 'test-error.com', 0);
-- INSERT INTO crawl_queue (url, status, nextfetchdate, host, depth) VALUES ('https://www.mailgun.com/', 'NEW', SYSTIMESTAMP, 'www.mailgun.com', 0);

COMMIT;

-- Show initial data
SELECT status, COUNT(*) as count
  FROM crawl_queue
 GROUP BY status
 ORDER BY status;