#!/bin/bash

# Run sqlplus in the Oracle container to check the queue status
docker exec -it oracle-test sqlplus c##mojtaba/bjnSY55l0g1IrzWY71Jg@//localhost:1521/XE << EOF
SELECT status, COUNT(*) FROM crawl_queue GROUP BY status;
SELECT * FROM crawl_queue WHERE ROWNUM <= 10;
EXIT;
EOF
