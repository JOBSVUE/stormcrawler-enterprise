#!/usr/bin/env bash
# ARCHITECTURE / SECURITY TODO:
# - Remove hardcoded JDBC_* secrets; rely on injected env or secret manager.
# - Derive jar name dynamically (parse target directory) to avoid mismatch.
# - Add metrics or timing around build & submission; consider skipping rebuild if unchanged.
# - Implement exponential backoff on submission retries.
set -euo pipefail

echo "==== STORM CRAWLER TOPOLOGY SUBMISSION SCRIPT ===="

# 1) Make sure we're in the crawler directory
cd /crawldata/crawler

# 2) Kill existing topology if it exists
echo "Checking for existing topology..."
if storm list | grep -q "crawler"; then
    echo "Found existing topology, killing it..."
    storm kill crawler -w 10 || true
    sleep 15
fi

# 3) Clean and build the project
echo "Building project..."
mvn clean package -DskipTests

# 4) Set environment variables for DB connection
export JDBC_URL="jdbc:oracle:thin:@//oracle-test:1521/XE"
export JDBC_USER="c##mojtaba"
export JDBC_PASS="bjnSY55l0g1IrzWY71Jg"

# Function to wait for a TCP port
wait_for_port() {
  local host=$1 port=$2 name=$3 timeout_secs=${4:-60}
  echo "Checking ${name} (${host}:${port})…"
  timeout ${timeout_secs} bash -c \
  "until echo > /dev/tcp/${host}/${port}; do
       echo \"Waiting for ${name}…\"
       sleep 5
     done"
  echo "${name} is ready!"
}

echo "Waiting for dependencies to be ready…"
wait_for_port oracle-test 1521 "Oracle database"
wait_for_port elasticsearch 9200 "Elasticsearch"
wait_for_port nimbus 6627 "Storm Nimbus"

# 5) Submit the topology with retries
echo "Submitting topology to Storm…"
max_retries=3
retry_count=0

until storm jar \
    target/stormcrawler-digitalpebble-1.0-SNAPSHOT.jar \
    org.apache.storm.flux.Flux \
    --remote \
    -c sql.connection.string="${JDBC_URL}" \
    -c sql.user="${JDBC_USER}" \
    -c sql.password="${JDBC_PASS}" \
    -c sql.status.table="crawl_queue" \
    crawler.flux
do
  retry_count=$((retry_count + 1))
  if [ "$retry_count" -ge "$max_retries" ]; then
    echo "ERROR: Topology submission failed after $max_retries attempts." >&2
    exit 1
  fi
  echo "Submission failed; retrying in 10 seconds (attempt $retry_count/$max_retries)…" >&2
  sleep 10
done

echo "==== TOPOLOGY SUBMITTED SUCCESSFULLY ===="
echo "You can now check the Storm UI at http://localhost:8080"
