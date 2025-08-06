#!/usr/bin/env bash
set -euo pipefail

# Validate environment variables
if [[ -z "${JDBC_URL:-}" || -z "${JDBC_USER:-}" || -z "${JDBC_PASS:-}" ]]; then
  echo "Error: Missing required environment variables." >&2
  echo "Ensure JDBC_URL, JDBC_USER, and JDBC_PASS are set." >&2
  exit 1
fi

# Load environment variables from .env file
if [ -f .env ]; then
  export $(cat .env | grep -v '^#' | xargs)
else
  echo "Error: .env file not found" >&2
  exit 1
fi

# 1) Give Storm user rw to our mounted code & repo folder
chmod -R a+rw /crawldata

# 2) Point Maven at a repo inside /crawldata
export MAVEN_OPTS=
export MAVEN_REPO_LOCAL="/crawldata/.repository"

# 3) Install Oracle JDBC driver into that local repo
mvn install:install-file \
  -Dmaven.repo.local="${MAVEN_REPO_LOCAL}" \
  -Dfile=/crawldata/crawler/lib/ojdbc8.jar \
  -DgroupId=com.oracle.database.jdbc \
  -DartifactId=ojdbc8 \
  -Dversion=19.3.0.0 \
  -Dpackaging=jar

# 4) Build & shade your topology
cd /crawldata/crawler
mvn clean package -Dmaven.repo.local="${MAVEN_REPO_LOCAL}"

# 5) Export your JDBC connection for the spout
export JDBC_URL="${JDBC_URL}"
export JDBC_USER="${JDBC_USER}"
export JDBC_PASS="${JDBC_PASS}"

# 6) Submit the topology to the remote Storm cluster, with retries
max_retries=5
retry_count=0

until storm jar \
    target/stormcrawler-digitalpebble-1.0-SNAPSHOT.jar \
    org.apache.storm.flux.Flux \
    --config crawler-conf.yaml \
    crawler.flux
do
  retry_count=$((retry_count + 1))
  if [ "$retry_count" -ge "$max_retries" ]; then
    echo "Topology submission failed after $max_retries attempts." >&2
    exit 1
  fi
  echo "Submission failed; retrying in 5 seconds (attempt $retry_count/$max_retries)..." >&2
  sleep 5
done

echo "Topology submitted successfully."
