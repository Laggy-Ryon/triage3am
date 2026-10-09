# 🎤 Triage3AM — Presentation Deck (PPT Structure & Speaker Notes)

> Use this exact 10-slide structure for your PowerPoint / Google Slides presentation. Each slide includes the key bullet points and speaker talk track.

---

### Slide 1: Title Slide
- **Title:** Triage3AM: Finding the Signal in 10,000 Log Lines at 3 A.M.
- **Subtitle:** Autonomous Log Clustering & Root-Cause Triage Engine
- **Event:** Protothon <> BST October 2026 | Problem Statement #8
- **Team Members:** [Add Your Team Names]
- **Speaker Note:** *"Good morning judges and mentors. Today we are presenting Triage3AM, an observability tool built to solve one of the most painful experiences in software engineering: getting paged at 3 a.m. and drowning in 10,000 lines of chaotic logs."*

---

### Slide 2: The 3 A.M. Nightmare (The Problem)
- **The Scenario:**
  - PagerDuty rings at 3:14 AM. Checkout service is down.
  - SRE opens logs: **10,000 lines of red text** across 6 microservices.
  - Interleaved stack traces, duplicate 504 timeouts, and retry storms.
- **The Core Problem:**
  - Finding **"Patient Zero"** (the first actual trigger) takes 45–60 minutes of manual grep and scroll.
  - Every minute of downtime costs \$5,000+ in e-commerce revenue.
- **Speaker Note:** *"When systems crash, they don't produce one clean error. They produce a tsunami of downstream casualties. Engineers spend the golden hour searching for Patient Zero in the dark."*

---

### Slide 3: Why Existing Solutions Fail
- **Brittle Regex Rules:** Break as soon as a library updates or a timestamp format shifts.
- **ELK / CloudWatch:** Show you *all* the logs, which magnifies the noise rather than reducing it.
- **Alert Fatigue:** Engineers mute alerts or guess the root cause under high stress.
- **Speaker Note:** *"Traditional log viewers store everything, but index nothing intelligently at the moment of crisis. Hand-written regex cannot keep up with dynamic microservices."*

---

### Slide 4: Introducing Triage3AM (The Proposed Solution)
- **What It Does:**
  - Ingests raw multi-service logs.
  - Clusters similar errors **dynamically without hand-written rules**.
  - Correlates chronological cascade & blast radius.
  - Pinpoints **Patient Zero** and outputs ready-to-run remediation runbooks.
- **The Benchmark:**
  - Turns **10,000 raw lines $\rightarrow$ 3 actionable incident cards** in **0.18 seconds**.
  - Delivers **99.92% noise reduction**.
- **Speaker Note:** *"Triage3AM is built on a single promise: turning 10,000 lines of noise into a handful of actionable incidents an engineer can act on inside 60 seconds."*

---

### Slide 5: Solution Workflow & Architecture
1. **Dynamic Token Masker:** Replaces UUIDs, IPs, memory addresses, and timestamps with generalized abstraction tokens.
2. **Drain-Style Prefix Tree Clustering:** Groups structural templates without regex rules.
3. **Temporal Cascade Engine:** Traces chronological propagation from root cause to downstream symptoms.
4. **Actionable Incident Synthesizer:** Computes impact score and matches deterministic remediation commands.
- **Speaker Note:** *"Our pipeline is completely rule-free. It uses structural token tree partitioning inspired by the Drain algorithm to cluster log templates in linear time, running completely in pure Python with zero heavy dependencies."*

---

### Slide 6: Live Prototype Demonstration
- **Scenario 1:** Black Friday Checkout Cascade (10,000 lines)
  - *Trigger:* `postgres-cluster` hits `max_connections=100`.
  - *Cascade:* HikariPool timeout $\rightarrow$ Payment RPC retry storm $\rightarrow$ 504 Gateway Timeouts.
  - *Result:* Triage3AM isolates `Line #2001` as Patient Zero in 0.18s and gives the exact `kubectl` fix!
- **Scenario 2:** Kubernetes OOM & CrashLoopBackOff (10,000 lines)
  - *Trigger:* Auth service memory leak and pod eviction.
  - *Result:* 99.92% noise reduction; ready-to-run rollback command.
- **Speaker Note:** *[Switch to screen share of http://localhost:8000 and click the 1-click preset button to show instant triage in under a second!]*

---

### Slide 7: The "War Room" Dashboard Features
- **Live Telemetry Ribbon:** Raw lines, Noise Reduction %, Triage Latency, Severity status.
- **Executive War Room Banner:** Instant root cause diagnosis + 1-click copyable terminal fix.
- **Visual Waterfall Timeline:** Shows exactly how the failure cascaded step-by-step.
- **Incident Cards:** Ranked by Impact (P0, P1, P2) with service blast radius.
- **1-Click Slack / PagerDuty Broadcast:** Formatted markdown for team communication.
- **Speaker Note:** *"The UI is designed specifically for an exhausted engineer at 3 a.m. No clutter, high contrast, immediate answers."*

---

### Slide 8: Impact & Value Proposition
- **MTTD Reduction:** Mean Time To Detect reduced from **45 minutes to <1 minute** (98% reduction).
- **Cost Savings:** Eliminates SLA breaches and downtime revenue loss.
- **Developer Well-being:** Cuts on-call stress, panic, and burnout.
- **Lightweight & Portable:** Zero external libraries needed; runs locally or in CI/CD / Kubernetes sidecars.
- **Speaker Note:** *"For an engineering team of 50, reducing outage resolution by 30 minutes per incident saves hundreds of thousands of dollars annually and keeps on-call rotations sustainable."*

---

### Slide 9: Future Roadmap
- **Real-time WebSocket Streaming:** Direct eBPF / FluentBit tailing for zero-latency live triage.
- **Automated Self-Healing:** Webhook triggers to auto-execute rollback scripts upon confidence threshold.
- **Multi-Cloud Integration:** Native AWS CloudWatch, GCP Cloud Logging, and Datadog connectors.

---

### Slide 10: Conclusion & Q&A
- **Summary:**
  - Solved Problem Statement #8 with a working, production-quality prototype.
  - 10,000 lines $\rightarrow$ 3 actionable incidents in 0.18s.
  - Rule-free clustering, Patient Zero isolation, and instant remediation.
- **Thank You!**
- **Repository:** `github.com/Laggy-Ryon/triage3am`
- **Speaker Note:** *"Thank you judges! We're ready for your questions."*
