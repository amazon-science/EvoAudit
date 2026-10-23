# Executor image for the WORKPLACE domain — a SELF-CONTAINED re-home of TAC.
#
# Unlike the original tac image (which was only an action surface curling live ownCloud/RocketChat),
# this image bakes the ENTIRE company state as plain files under /workspace, exactly like the
# devops/fintech domains. "Services" are local Python engines that deterministically mutate JSON:
#   /workspace/files/  (ownCloud tree + share table)   <- _owncloud_engine.py via owncloud_api.sh
#   /workspace/chat/   (channels, messages, membership) <- _chat_engine.py    via rocketchat_api.sh
# Reset between arms is a fresh container (DockerSandbox.reset_workspace: docker rm -f + run), so
# there is NO host-side reset, NO mongorestore, NO lanes, NO --network/--add-host. Runs launch with
# no service flags, like devops/fintech.
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
# Self-contained state means we can pin an in-world clock again (tac had to run at real time only
# because live services stamped real timestamps). The executor wraps each command in faketime when
# SCENARIO_TIME is set; each task declares its own absolute clock in tasks.json. Empty default so a
# direct container run is not silently governed by a stale date.
ENV SCENARIO_TIME=""
ENV FAKETIME_DONT_FAKE_MONOTONIC=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY task_executor_api.py .
COPY workspace/ /workspace/

# Make the wrappers + engines executable; _svc_common.sh is sourced by the wrappers.
RUN chmod +x /workspace/scripts/*.sh || true

# Deliverables and the action log live under /workspace. The action log ships with a header so the
# harness snapshot (which records a path only when `cat` is non-empty) always captures it.
RUN mkdir -p /workspace/reports

# Opaque build digest — compared against tasks.json build_digest by the harness preflight so a run
# cannot silently execute against a stale image.
RUN echo "c3e2b00b1e5a4d0b" > /etc/img_build.digest

EXPOSE 5000

CMD ["python", "task_executor_api.py"]
