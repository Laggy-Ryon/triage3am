"""
Dataset Generator for Triage3AM: Generates realistic 10,000-line enterprise outage logs
with buried root-cause triggers, cascading downstream failures, and background noise.
"""

import random
import uuid
from datetime import datetime, timedelta

def generate_scenario_1_db_exhaustion(total_lines=10000) -> str:
    """Scenario 1: E-Commerce Black Friday Checkout Cascade (PostgreSQL Pool Starvation)"""
    services = ['api-gateway', 'order-service', 'inventory-service', 'payment-gateway', 'user-service', 'postgres-cluster']
    base_time = datetime(2026, 10, 10, 3, 0, 0)
    lines = []

    # Phase 1: Normal traffic (first 2,000 lines)
    for i in range(2000):
        t = base_time + timedelta(seconds=i * 0.05)
        svc = random.choice(services[:5])
        req_id = uuid.uuid4().hex[:8]
        lines.append(f"{t.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z [{svc}] INFO  req_{req_id} 200 OK GET /api/v1/health duration={random.randint(4, 25)}ms")

    # Phase 2: Patient Zero Trigger at 03:02:11
    t_trigger = datetime(2026, 10, 10, 3, 2, 11)
    lines.append(f"{t_trigger.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z [postgres-cluster] FATAL remaining connection slots are reserved for non-replication superuser connections (max_connections=100) pid={random.randint(1000, 9999)}")
    lines.append(f"{t_trigger.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z [postgres-cluster] ERROR db-primary-01: terminating connection due to administrator command, pool exhausted for user app_orders")

    # Phase 3: Cascade starts (Next 8,000 lines mixed with errors and desperate retries)
    error_pool = [
        "[order-service] ERROR HikariPool-1 - Connection is not available, request timed out after 30002ms client_id={client_id}",
        "[payment-gateway] ERROR Transaction rollback failed: Connection pool exhausted while processing order {order_id}",
        "[api-gateway] WARN Upstream order-service response delayed > 5000ms for route /api/v1/checkout",
        "[api-gateway] ERROR 504 Gateway Timeout POST /api/v1/orders/checkout client_ip={ip} latency=30005ms",
        "[inventory-service] ERROR Database lock acquisition timeout on sku_{sku}: could not obtain lock on relation 'inventory_items'",
        "[order-service] ERROR Unhandled rejection in OrderProcessorWorker: ConnectionClosedException at /app/src/db.ts:142",
        "[payment-gateway] ERROR PaymentIntent pi_{uuid} failed: remote RPC timed out after 3 retries",
    ]

    curr_time = t_trigger
    for i in range(total_lines - len(lines)):
        curr_time += timedelta(milliseconds=random.randint(5, 50))
        # 40% noise, 60% cascade errors
        if random.random() < 0.35:
            svc = random.choice(['user-service', 'inventory-service', 'api-gateway'])
            req_id = uuid.uuid4().hex[:8]
            lines.append(f"{curr_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z [{svc}] INFO req_{req_id} GET /static/assets/logo.png 200 OK")
        else:
            tmpl = random.choice(error_pool)
            formatted = tmpl.format(
                client_id=random.randint(10000, 99999),
                order_id=f"ord_{uuid.uuid4().hex[:6]}",
                ip=f"192.168.1.{random.randint(10, 250)}",
                sku=random.randint(100, 999),
                uuid=uuid.uuid4().hex[:12]
            )
            lines.append(f"{curr_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z {formatted}")

    return "\n".join(lines)


def generate_scenario_2_k8s_oom(total_lines=10000) -> str:
    """Scenario 2: Kubernetes OOMKilled & Cascading CrashLoopBackOff"""
    base_time = datetime(2026, 10, 10, 3, 14, 0)
    lines = []

    # Normal prelude
    for i in range(1500):
        t = base_time + timedelta(seconds=i * 0.04)
        lines.append(f"{t.strftime('%Y-%m-%d %H:%M:%S')} [auth-service] INFO Token verified for user_{random.randint(100, 999)} in 12ms")

    # Patient Zero at 03:14:52
    t_oom = datetime(2026, 10, 10, 3, 14, 52)
    lines.append(f"{t_oom.strftime('%Y-%m-%d %H:%M:%S')} [auth-service] CRITICAL java.lang.OutOfMemoryError: Java heap space at com.auth.jwt.TokenCache.allocate(TokenCache.java:412)")
    lines.append(f"{t_oom.strftime('%Y-%m-%d %H:%M:%S')} [node-worker-04] CRITICAL oom-killer: killed process 14092 (java) total-vm:2097152kB, anon-rss:1048576kB cgroup=/kubepods/burstable/auth-service")
    lines.append(f"{t_oom.strftime('%Y-%m-%d %H:%M:%S')} [kubelet] ERROR Container auth-service in pod auth-service-7d8f9b4c-kx92z failed liveness probe, restarting")

    error_templates = [
        "[api-gateway] ERROR Upstream connection failed: connect ECONNREFUSED auth-service:8080 during /oauth/token",
        "[user-service] ERROR AuthTokenValidationException: cannot reach auth-service cluster IP 10.96.42.18:8080",
        "[order-service] ERROR Unauthorized request rejected due to auth-service timeout on authorization header Bearer {token}",
        "[kubelet] WARN Back-off restarting failed container auth-service in pod auth-service-7d8f9b4c-kx92z (CrashLoopBackOff)",
        "[api-gateway] ERROR 502 Bad Gateway while authenticating session sid_{sid}"
    ]

    curr_time = t_oom
    for i in range(total_lines - len(lines)):
        curr_time += timedelta(milliseconds=random.randint(4, 40))
        if random.random() < 0.3:
            lines.append(f"{curr_time.strftime('%Y-%m-%d %H:%M:%S')} [kube-proxy] INFO Updated endpoints for service kube-dns: 10.244.0.3:53")
        else:
            tmpl = random.choice(error_templates)
            formatted = tmpl.format(
                token=uuid.uuid4().hex[:16],
                sid=uuid.uuid4().hex[:8]
            )
            lines.append(f"{curr_time.strftime('%Y-%m-%d %H:%M:%S')} {formatted}")

    return "\n".join(lines)


def generate_scenario_3_redis_thundering_herd(total_lines=10000):
    lines = []
    base_time = datetime(2026, 10, 10, 3, 30, 0)
    
    for i in range(1500):
        base_time += timedelta(milliseconds=random.randint(10, 50))
        lines.append(f"{base_time.strftime('%Y-%m-%d %H:%M:%S')} [cache-proxy] INFO Cache hit for key product:{random.randint(100, 999)}")
        
    base_time += timedelta(milliseconds=random.randint(10, 50))
    lines.append(f"{base_time.strftime('%Y-%m-%d %H:%M:%S')} [redis-cluster] PANIC Master failover timed out. Sentinel could not promote replica. Cluster state: FAIL")
    
    error_templates = [
        "[cache-proxy] ERROR Connection refused to redis-cluster:6379, falling back to DB",
        "[product-service] WARN Cache miss, fetching from db-primary",
        "[product-service] ERROR HikariPool-1 - Connection is not available, request timed out after 30000ms",
        "[search-service] ERROR Timeout fetching product metadata, search degraded",
        "[api-gateway] ERROR 504 Gateway Timeout while routing to product-service for path /api/v1/products/{pid}"
    ]
    
    for i in range(total_lines - 1501):
        base_time += timedelta(milliseconds=random.randint(5, 30))
        if random.random() < 0.3:
            lines.append(f"{base_time.strftime('%Y-%m-%d %H:%M:%S')} [kubelet] INFO Node health check OK for node-pool-1")
        else:
            tmpl = random.choice(error_templates)
            formatted = tmpl.format(pid=random.randint(1000, 9999))
            lines.append(f"{base_time.strftime('%Y-%m-%d %H:%M:%S')} {formatted}")
            
    return "\n".join(lines)


if __name__ == '__main__':
    import os
    random.seed(42)
    uuid.uuid4 = lambda: uuid.UUID(int=random.getrandbits(128))
    os.makedirs('datasets', exist_ok=True)
    
    print("Generating Scenario 1: 10,000 log lines (DB Connection Pool Exhaustion)...")
    s1 = generate_scenario_1_db_exhaustion(10000)
    with open('datasets/ecommerce_cascade_10k.log', 'w') as f:
        f.write(s1)
        
    print("Generating Scenario 2: 10,000 log lines (Kubernetes OOM & CrashLoopBackOff)...")
    s2 = generate_scenario_2_k8s_oom(10000)
    with open('datasets/k8s_oom_cascade_10k.log', 'w') as f:
        f.write(s2)

    print("Generating Scenario 3: 10,000 log lines (Redis Thundering Herd)...")
    s3 = generate_scenario_3_redis_thundering_herd(10000)
    with open('datasets/redis_thundering_herd_10k.log', 'w') as f:
        f.write(s3)

    print("Datasets successfully created in ./datasets/")
