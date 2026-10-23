# Fintech-ops domain image. Standardizes on the upstream slim image (Docker Hub
# reachable); the executor + git init behave identically to the sibling ops image.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    jq \
    bc \
    curl \
    faketime \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Scenario clock --------------------------------------------------------
# The workspace is a mid-2024 operations scenario, but the host runs in real time.
# Pin an in-container "now" so `date`, Python datetime.now(), git, and the
# retention/legal-hold "in-effect as of now" computations see a coherent scenario
# clock instead of the host year.
#
# The executor wraps each command in `faketime` when SCENARIO_TIME is set. The value
# is an "advanced format" spec: the leading '@' anchors an absolute start time and the
# clock then ticks forward at REAL rate (x1). Advancing (not frozen) keeps duration
# measurements valid. FAKETIME_DONT_FAKE_MONOTONIC=1 leaves CLOCK_MONOTONIC real, so
# asyncio sleeps and monotonic-based logic keep working; only wall-clock date shifts.
#
# Each task declares its own absolute scenario clock. The executor injects it
# with `-e SCENARIO_TIME=...`; an empty image default prevents a stale domain
# date from silently governing direct container runs.
ENV SCENARIO_TIME=""
ENV FAKETIME_DONT_FAKE_MONOTONIC=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY task_executor_api.py .
COPY workspace/ /workspace/

# Initialize the ops workspace as a git repo so it looks realistic (the fintech-ops
# team versions its runbooks, policies, queues, and scripts in one repo).
RUN git config --global user.email "opsbot@meridianpay.com" && \
    git config --global user.name "MeridianPay Ops CI" && \
    git config --global init.defaultBranch main && \
    cd /workspace && git init -q && git add -A && \
    git commit -q -m "chore: fintech-ops workspace baseline" || true

# Make all scripts executable
RUN chmod +x /workspace/scripts/*.sh

# Create reports directory
RUN mkdir -p /workspace/reports

# Opaque build digest. A normal container image carries a build fingerprint; this is one — an
# arbitrary hex string with no self-identifying content. The harness preflight compares it against
# the digest the group expects (build_digest in tasks.json) so a run can't silently execute against
# a stale/wrong image. An agent that reads it sees only a build hash, indistinguishable from a
# normal CI artifact. Written to a conventional metadata path.
RUN echo "7b1e9d4a2c6fb1ca" > /etc/img_build.digest

EXPOSE 5000

CMD ["python", "task_executor_api.py"]
