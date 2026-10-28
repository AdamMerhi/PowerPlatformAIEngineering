# Claims PDS Agent API.
# Stage 1 installs dependencies and BUILDS the vector index (and downloads the small embedding model) from docs/pds/.
# Stage 2 is the runtime image: the index and model are read-only files inside it, so there is no hosted vector
# service and no idle cost, and a PDS change is a reviewed commit that produces a new image.
FROM python:3.13-slim AS build
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 FASTEMBED_CACHE_PATH=/models
COPY requirements-agent.txt .
RUN pip install --prefix=/install -r requirements-agent.txt
COPY agent_api agent_api
COPY claims_pipeline claims_pipeline
COPY docs docs
ENV PYTHONPATH=/install/lib/python3.13/site-packages
RUN python -m agent_api.index_build /index

FROM python:3.13-slim
# Links the package to this repository so the workflow's GITHUB_TOKEN may create and push it on GHCR.
LABEL org.opencontainers.image.source="https://github.com/AdamMerhi/PowerPlatformAIEngineering"
LABEL org.opencontainers.image.description="Claims PDS Agent API (Advisor and Verifier)"
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /install /usr/local
COPY --from=build /models /models
COPY --from=build /index /index
COPY agent_api agent_api
COPY claims_pipeline claims_pipeline
COPY docs docs
ENV FASTEMBED_CACHE_PATH=/models AGENT_INDEX_DIR=/index HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
USER app
EXPOSE 8080
CMD ["uvicorn", "agent_api.app:app", "--host", "0.0.0.0", "--port", "8080"]
