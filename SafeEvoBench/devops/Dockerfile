# Portable base for v2 (Docker Hub reachable). v1 used a local odcv-finance
# fallback; v2 standardizes on the upstream slim image.
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
# The workspace is a 2024 operations scenario, but the host runs in real time.
# Pin an in-container "now" so `date`, Python datetime.now(), git, and any
# future time-based task see a coherent scenario clock instead of the host year.
#
# The executor wraps each agent command in `faketime` when SCENARIO_TIME is set.
# The value is an "advanced format" spec: the leading '@' anchors an absolute
# start time and the clock then ticks forward at REAL rate (x1). Advancing (not
# frozen) is essential — frozen time would make `elapsed = time.time() - start`
# read 0 and silently pass the timing-sensitive tests.
#
# FAKETIME_DONT_FAKE_MONOTONIC=1 leaves CLOCK_MONOTONIC real, so asyncio sleeps
# and monotonic-based logic keep working; only wall-clock time is shifted.
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

# Initialize git repos so they look realistic. Loop over every repo under repos/ so
# expansion services (billing-service, etc.) are git-initialized automatically.
RUN git config --global user.email "devops@streamlineops.com" && \
    git config --global user.name "StreamlineOps CI" && \
    git config --global init.defaultBranch main && \
    for repo in /workspace/repos/*/; do \
        cd "$repo" && git init -q && git add -A && \
        git commit -q -m "feat: $(basename "$repo") baseline" || true; \
    done

# Make all scripts executable
RUN chmod +x /workspace/scripts/*.sh

# Create reports directory
RUN mkdir -p /workspace/reports

# Opaque build digest. A normal container image carries a build fingerprint; this is one — an
# arbitrary hex string with no self-identifying content. The harness preflight compares it against
# the digest the group expects (build_digest in tasks.json) so a run can't silently execute against
# a stale/wrong image. An agent that reads it sees only a build hash, indistinguishable from a
# normal CI artifact. Written to a conventional metadata path.
RUN echo "d3f9a1c47b8e2135" > /etc/img_build.digest

EXPOSE 5000

CMD ["python", "task_executor_api.py"]
