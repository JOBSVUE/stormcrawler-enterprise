#!/bin/bash

# Monitor all relevant logs
docker-compose logs -f --tail=100 oracle-test nimbus supervisor runner
