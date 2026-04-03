---
name: root_cause_analysis
description: "Perform AI-driven root cause analysis using Prometheus metrics and ELK (Elasticsearch/Kibana) logs. When the user reports an incident, anomaly, alert, or performance degradation, use this skill to query metrics and logs, correlate signals across time, and produce a structured root cause report with findings and remediation suggestions."
metadata:
  {
    "builtin_skill_version": "1.0",
    "copaw":
      {
        "emoji": "🔍",
        "requires": {}
      }
  }
---

# Root Cause Analysis (Prometheus + ELK)

This skill enables AI-driven root cause analysis by correlating Prometheus metrics with ELK logs around an incident window.

---

## Workflow Overview

```
User describes incident
        ↓
1. Clarify scope (service, time window, symptom)
        ↓
2. Query Prometheus for anomalous metrics
        ↓
3. Query Elasticsearch for correlated error logs
        ↓
4. Correlate signals (time alignment, common labels)
        ↓
5. Output structured root cause report
```

---

## Step 1 — Clarify Scope

Before querying any data, confirm:

| Parameter | Example |
|-----------|---------|
| **Service / target** | `payment-service`, `api-gateway`, `mysql` |
| **Incident start time** | `2024-03-15 14:30:00` (UTC preferred) |
| **Duration** | `30m`, `1h` |
| **Symptom** | `high error rate`, `latency spike`, `OOM`, `CPU spike` |
| **Alert name (if any)** | `HighErrorRate`, `PodCrashLooping` |

If the user doesn't provide a time window, default to **last 1 hour**.

---

## Step 2 — Query Prometheus Metrics

Use `execute_shell_command` or `http_request` to call the Prometheus HTTP API.

### Base URL

```
PROMETHEUS_URL = http://<prometheus-host>:9090
```

Ask the user for the Prometheus URL if not configured as an env var.

### Query anomalous metrics — key PromQL templates

#### Error rate (HTTP 5xx)
```promql
sum(rate(http_requests_total{job="<service>", status=~"5.."}[5m])) by (service)
/
sum(rate(http_requests_total{job="<service>"}[5m])) by (service)
```

#### P99 latency
```promql
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket{job="<service>"}[5m])) by (le, service)
)
```

#### CPU usage
```promql
sum(rate(container_cpu_usage_seconds_total{container="<service>"}[5m])) by (pod)
```

#### Memory usage
```promql
container_memory_usage_bytes{container="<service>"}
  / container_spec_memory_limit_bytes{container="<service>"}
```

#### Pod restarts
```promql
increase(kube_pod_container_status_restarts_total{container="<service>"}[1h])
```

#### Downstream dependency error rate
```promql
sum(rate(http_requests_total{job="<downstream-service>", status=~"5.."}[5m])) by (service)
```

### How to call Prometheus API

```bash
# Instant query
curl -G "http://<prometheus>:9090/api/v1/query" \
  --data-urlencode 'query=up' \
  --data-urlencode 'time=2024-03-15T14:30:00Z'

# Range query (for trend)
curl -G "http://<prometheus>:9090/api/v1/query_range" \
  --data-urlencode 'query=rate(http_requests_total[5m])' \
  --data-urlencode 'start=2024-03-15T14:00:00Z' \
  --data-urlencode 'end=2024-03-15T15:00:00Z' \
  --data-urlencode 'step=30s'
```

### Analysis focus

- Look for **spikes or drops** relative to the 30 min before the incident
- Check if the anomaly started **before or after** the user-reported time
- Identify which **labels** (pod, node, endpoint) are most affected

---

## Step 3 — Query Elasticsearch Logs

Use `execute_shell_command` or `http_request` to call the Elasticsearch REST API.

### Base URL

```
ELASTICSEARCH_URL = http://<elasticsearch-host>:9200
```

### Query error logs around incident window

```bash
curl -s -X GET "http://<elasticsearch>:9200/<index-pattern>/_search" \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 100,
    "sort": [{"@timestamp": {"order": "asc"}}],
    "query": {
      "bool": {
        "must": [
          {"range": {
            "@timestamp": {
              "gte": "<incident_start - 5m>",
              "lte": "<incident_start + 30m>"
            }
          }},
          {"terms": {"level": ["ERROR", "FATAL", "WARN"]}},
          {"match": {"service": "<service-name>"}}
        ]
      }
    },
    "aggs": {
      "error_over_time": {
        "date_histogram": {
          "field": "@timestamp",
          "fixed_interval": "1m"
        }
      },
      "top_errors": {
        "terms": {"field": "message.keyword", "size": 10}
      }
    }
  }'
```

### Common index patterns

| Stack | Index Pattern |
|-------|--------------|
| Kubernetes + Fluentd | `kubernetes-*` |
| Filebeat | `filebeat-*` |
| Logstash | `logstash-*` |
| APM | `apm-*` |

Ask the user for the index pattern if unknown.

### Log analysis focus

- Find the **first occurrence** of ERROR logs — this often points to the root cause
- Extract **exception types, stack traces, error messages**
- Identify **log volume spikes** (sudden increase in error logs = symptom onset)
- Look for **upstream/downstream** service names in error messages

---

## Step 4 — Correlate Signals

After collecting metrics and logs, apply the following correlation logic:

### Time correlation

1. Find the **earliest anomaly timestamp** across all signals
2. The earliest signal is likely the root cause; later signals are cascading effects
3. Build a timeline:

```
T-0  [Prometheus] pod_restarts increased for payment-db
T+2m [Prometheus] error_rate spiked for payment-service
T+3m [ELK]        ERROR: connection refused to payment-db
T+5m [Prometheus] latency P99 spiked for api-gateway
T+6m [ELK]        ERROR: timeout calling payment-service
```

### Label / service correlation

- Match Prometheus **labels** (pod, namespace, service) with ELK **fields** (service, k8s.pod.name)
- If a single pod/node appears in both metrics and logs as anomalous → strong signal

### Causal chain inference

Use these heuristics:

| Metric pattern | Likely cause |
|----------------|-------------|
| Pod restarts → high error rate downstream | Application crash / OOM |
| DB connection errors + CPU spike on DB | DB overload / slow queries |
| DNS errors in logs + network metrics anomaly | Network / DNS issue |
| Deployment event (new pod versions) at T-0 | Bad deployment |
| Certificate expiry errors | TLS cert expired |
| 429 Too Many Requests in logs | Rate limiting / quota exceeded |

---

## Step 5 — Output Root Cause Report

Always produce a structured report:

```markdown
## Root Cause Analysis Report

**Incident:** <brief description>
**Time Window:** <start> — <end>
**Affected Service:** <service name>

### Timeline of Events
| Time | Source | Signal | Value |
|------|--------|--------|-------|
| 14:28 | Prometheus | payment-db pod restarts | +5 in 10m |
| 14:30 | ELK | ERROR: connection refused | 3,421 occurrences |
| 14:31 | Prometheus | payment-service error_rate | 45% |
| 14:33 | Prometheus | api-gateway P99 latency | 8.2s |

### Root Cause
**Primary:** payment-db pod crashed due to OOM (memory limit exceeded).
**Evidence:**
- `container_memory_usage_bytes / limit` reached 99.8% at 14:26
- Pod restart count increased by 5 between 14:26–14:30
- First ERROR log "connection refused to payment-db" appeared at 14:30:03

### Cascading Effects
1. payment-service lost DB connections → returned 500 errors
2. api-gateway retried → latency spike

### Recommendations
1. **Immediate:** Increase payment-db memory limit from 512Mi to 1Gi
2. **Short-term:** Add connection pool retry with exponential backoff in payment-service
3. **Long-term:** Set up Prometheus alert for memory usage > 80% on DB pods

### Confidence
High — metrics and logs corroborate the same root cause with clear time ordering.
```

---

## Configuration Reference

If Prometheus or Elasticsearch require authentication:

### Prometheus with basic auth
```bash
curl -u admin:password -G "http://<prometheus>:9090/api/v1/query" ...
```

### Elasticsearch with API key
```bash
curl -H "Authorization: ApiKey <base64-encoded-key>" \
  "http://<elasticsearch>:9200/_search" ...
```

### Common environment variables to ask the user about
```
PROMETHEUS_URL      Prometheus base URL
ELASTICSEARCH_URL   Elasticsearch base URL
ES_INDEX            Elasticsearch index pattern (e.g., kubernetes-*)
ES_API_KEY          Elasticsearch API key (if auth required)
```

---

## Tips

- Always query a **5-minute buffer before** the reported incident time — root causes often precede user-reported symptoms
- When multiple anomalies exist simultaneously, use **temporal ordering** to determine root vs symptom
- If Prometheus and ELK show **no anomalies**, check: infrastructure layer (node metrics, network), external dependencies, or recent deployments
- For recurring incidents, compare current signals with **previous incident patterns** to identify if this is the same root cause
- Use `increase()` instead of `rate()` in Prometheus when querying discrete events like restarts or errors over a fixed window
