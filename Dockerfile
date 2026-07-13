FROM python:3.11-slim

LABEL org.opencontainers.image.title="Falses Goofish GuardAgent" \
      org.opencontainers.image.description="Extensible Xianyu customer-service agent with deterministic guardrails" \
      org.opencontainers.image.source="https://github.com/falses00/Falses-Goofish-GuardAgent"

ENV TZ=Asia/Shanghai \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NON_INTERACTIVE=true

WORKDIR /app

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY main.py XianyuAgent.py XianyuApis.py context_manager.py ./
COPY core/ core/
COPY utils/ utils/
COPY api/ api/
COPY prompts/ prompts/
COPY data/*.json data/
COPY evals/ evals/
COPY tools/ tools/

RUN addgroup --system --gid 10001 guardagent \
    && adduser --system --uid 10001 --ingroup guardagent --home /app guardagent \
    && mkdir -p logs output \
    && python -m py_compile main.py XianyuAgent.py context_manager.py core/*.py api/*.py \
    && chown -R guardagent:guardagent /app

USER guardagent

CMD ["python", "main.py", "--mode", "xianyu"]
