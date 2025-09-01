#!/usr/bin/env bash
# ARCHITECTURE / SECURITY TODO:
# - Remove hardcoded JDBC_* secrets; rely on injected env or secret manager.
# - Derive jar name dynamically (parse target directory) to avoid mismatch.
# - Add metrics or timing around build & submission; consider skipping rebuild if unchanged.
# - Implement exponential backoff on submission retries.
set -euo pipefail

echo "==== STORM CRAWLER TOPOLOGY SUBMISSION SCRIPT ===="

# Topology name (override with TOPOLOGY_NAME env)
TOPOLOGY_NAME="${TOPOLOGY_NAME:-stormcrawler-enterprise}"

# 1) Make sure we're in the crawler directory
cd /crawldata/crawler

# 2) Kill existing topology if it exists
echo "Checking for existing topology '${TOPOLOGY_NAME}'..."
if storm list | grep -wq "${TOPOLOGY_NAME}"; then
    echo "Found existing topology '${TOPOLOGY_NAME}', killing it..."
    storm kill "${TOPOLOGY_NAME}" -w 10 || true
    sleep 15
fi

# 3) Clean and build the project
echo "Building project..."
# Optional: skip rebuild if SKIP_BUILD=1 is set and a jar is present
SKIP_BUILD="${SKIP_BUILD:-0}"
build_start_ts=$(date +%s)
if [ "$SKIP_BUILD" != "1" ]; then
  mvn clean package -DskipTests
else
  echo "SKIP_BUILD=1 -> skipping Maven build"
fi
build_end_ts=$(date +%s)

# Resolve the most recent shaded jar dynamically
resolve_jar() {
  ls -1t target/*-SNAPSHOT.jar target/*.jar 2>/dev/null | head -n1 || true
}
JAR_PATH="$(resolve_jar)"
if [ -z "${JAR_PATH}" ]; then
  echo "No JAR found in target/. Forcing a build..."
  mvn clean package -DskipTests
  JAR_PATH="$(resolve_jar)"
fi
if [ -z "${JAR_PATH}" ]; then
  echo "ERROR: Could not find a jar in target/ after build." >&2
  exit 1
fi
echo "Using JAR: ${JAR_PATH}"

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
wait_for_port extractor 8000 "Extractor API"
wait_for_port js-renderer 8001 "JS Renderer"

# 5) Submit the topology with retries
echo "Submitting topology to Storm…"
max_retries=3
retry_count=0
sleep_backoff=5  # exponential backoff start (seconds), doubled per retry (max 60s)

# Allow runtime override of crawl depth (default 2 to include sitemap URLs)
SPOUT_MAX_DEPTH="${SPOUT_MAX_DEPTH:-2}"

submit_start_ts=$(date +%s)
until storm jar \
    "${JAR_PATH}" \
    org.apache.storm.flux.Flux \
    --remote \
    -c topology.name="${TOPOLOGY_NAME}" \
    -c sql.connection.string="${JDBC_URL}" \
    -c sql.user="${JDBC_USER}" \
    -c sql.password="${JDBC_PASS}" \
    -c sql.status.table="crawl_queue" \
    -c spout.max.depth="${SPOUT_MAX_DEPTH}" \
    src/main/resources/base-topology.flux
do
  retry_count=$((retry_count + 1))
  if [ "$retry_count" -ge "$max_retries" ]; then
    echo "ERROR: Topology submission failed after $max_retries attempts." >&2
    exit 1
  fi
  echo "Submission failed; retrying in ${sleep_backoff}s (attempt $retry_count/$max_retries)…" >&2
  sleep "${sleep_backoff}"
  # Exponential backoff with cap
  sleep_backoff=$(( sleep_backoff * 2 ))
  if [ "${sleep_backoff}" -gt 60 ]; then sleep_backoff=60; fi
done
submit_end_ts=$(date +%s)

echo "Build time: $((build_end_ts - build_start_ts))s; Submission time: $((submit_end_ts - submit_start_ts))s"
echo "==== TOPOLOGY SUBMITTED SUCCESSFULLY ===="
echo "You can now check the Storm UI at http://localhost:8080"
