#!/bin/sh
mkdir -p /logs/verifier
if [ "$(cat /app/answer.txt 2>/dev/null)" = QWENPAW_SMOKE_OK ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
