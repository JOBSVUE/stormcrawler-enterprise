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

-- 4) Seed the table with test URLs using NEW status
--INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.varzesh3.com/sitemap/news', 'NEW', SYSTIMESTAMP, 'www.varzesh3.com');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://yjc.ir/en', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/religion', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/52129/al-nujaba-spox-the-american-attack-on-border-guards-was-in-response-to-pmf-military-parade-and-was-aimed-at-reviving-daesh', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/50967/international-quran-competition-wraps-up-in-tehran', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/51053/iran-calls-for-muslim-unity-against-west%E2%80%99s-islamophobia-campaign', 'NEW', SYSTIMESTAMP, 'yjc.ir');

-- Newly added URLs
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/54036/pompeo-being-tougher-on-iran-is-biden%E2%80%99s-key-to-saudi-arabia-israel-normalization', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/54014/texas-constable-deputy-fatally-shot', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/56157/deep-pocket-who-were-on-epsteins-pocket-list', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/55906/no-united-states-equals-peace', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/55383/he-is-bad-news', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/55351/sanders-us-is-not-able-to-afford-its-basic-medical-needs', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/55350/the-rise-of-islamophobia', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/55275/the-united-states-captures-saddam-hussein-former-leader-of-iraq', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/55260/zionists-in-charge', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/55198/the-truth-behind-mbs-relation-with-the-us', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/55172/firearms-in-the-us-statistics-and-facts', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/55067/disaster-land', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/54690/malcolm-x%E2%80%99s-daughter-malikah-shabazz-found-dead-in-nyc-home', 'NEW', SYSTIMESTAMP, 'yjc.ir');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://www.yjc.ir/en/news/51305/stop-lying-muslim-advocacy-group-sues-facebook-over-claims-it-removes-hate-speech-hate-speech', 'NEW', SYSTIMESTAMP, 'yjc.ir');

-- Additional status values for testing
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://test-fetched.com', 'FETCHED', SYSTIMESTAMP, 'test-fetched.com');
INSERT INTO crawl_queue (url, status, nextfetchdate, host) VALUES ('https://test-error.com', 'ERROR', SYSTIMESTAMP, 'test-error.com');

COMMIT;

-- Show initial data
SELECT status, COUNT(*) as count
  FROM crawl_queue
 GROUP BY status
 ORDER BY status;