
FROM storm:2.7.0

USER root
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y maven openjdk-11-jdk \
 && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
USER storm
WORKDIR /home/storm
