#!/bin/bash

# Script to add a URL to the crawl queue
# Usage: ./add-url.sh "https://example.com/page1"

if [ -z "$1" ]; then
  echo "Usage: ./add-url.sh URL"
  exit 1
fi

URL=$1

# Run sqlplus in the Oracle container
docker exec -it oracle-test sqlplus c##mojtaba/bjnSY55l0g1IrzWY71Jg@//localhost:1521/XE << EOF
INSERT INTO crawl_queue (url, status) VALUES ('$URL', 'NEW');
COMMIT;
EXIT;
EOF

echo "URL added: $URL"
