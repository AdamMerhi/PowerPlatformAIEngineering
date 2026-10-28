# PLAN

Handoff document. Read `CLAUDE.md` first, then this file. Last updated 2026-10-28 (DAG C built).

## Goal

A 2-day POC, "Claims PDS Agent", that shows every focus area of the Intelligent Automation Engineer role by solving one insurance problem.

**Problem.** In May 2024 Zurich declined two trauma claims by telling the policyholders their conditions were excluded. ASIC alleges the policy did not exclude them and issued two infringement notices totalling $37,560 in May 2025 (ASIC release 25-077MR). Zurich found the error in a quality assurance review and paid both claims with interest.

**Solution.** An agent reads each new claim and the Product Disclosure Statement (PDS), recommends accept or decline with the clause cited, and a second pass re-checks every submitted decision against the PDS. A report covers the whole claims log. A person decides every claim.

## Architecture (4 containers)

Diagram: https://claude.ai/artifact/L8rWMDhex8qzUuiFbmFjhZ (private to the owner).

- **Snowflake:** claims tables (RAW, CLEAN, CURATED, task DAG), PDS vector store holding sparse embeddings (source of truth), agent results tables, masking policies and RBAC.
- **Azure platform:** Apache Airflow (DAG A parse and embed the PDS, DAG B load Qdrant, DAG C ingest public claims, DAG D sync CURATED to Dataverse by REST + OAuth), Qdrant for sparse search, Key Vault, Agent API (Reader, Advisor, Verifier, Reporter).
- **Azure AI (Foundry project):** Azure OpenAI chat model, Document Intelligence (optional), Language service for PII redaction, Content Safety.
- **Power Platform:** Copilot Studio agent (the chat is the only interface), canvas app hosting the chat plus an approve/override card, model-driven app for the claims log and audit trail, Power Automate flows as agent tools, Dataverse.
- **Cross-cutting:** Azure DevOps pipelines, security by design, governance framework.

### Run order
1. DAG A: PDS PDF to Document Intelligence, chunk, fastembed sparse vectors, Snowflake.
2. DAG B: Snowflake vectors to Qdrant.
3. DAG C: public claims data into Snowflake RAW.
4. DAG D: CURATED to Dataverse (REST + Entra OAuth).
5. Adjuster asks the chat for new claims. Power Automate calls the Agent API: Reader, Advisor (retrieve PDS clauses, Azure OpenAI summary and recommendation, PII redacted first, outputs safety-filtered).
6. Adjuster confirms or overrides. Decision saved to Dataverse and Snowflake with reason and clause IDs.
7. Verifier re-checks each decision against the PDS and flags unsupported declines.
8. Reporter builds the claims-log report.

## Decisions made

- **2-day slice, cheap stack.** Airflow in Docker Compose on one small VM (deallocate when idle), Qdrant embedded in the Agent API and rebuilt from Snowflake at start-up, Agent API on Container Apps scaled to zero, one chat model deployed (no embedding model, fastembed runs locally), free tiers for Language, Content Safety and Document Intelligence. No AKS.
- **Orchestration.** Plain OpenAI SDK with function calling unless the owner already knows LangChain/LangGraph.
- **Front end.** Canvas app embeds the Copilot Studio agent. Embed method must be tested first on day 2.
- **Public claims data.** DAG C's source is settled: `dataCar` from the CRAN R package `insuranceData` — 67,856 real Australian third-party motor policies (2004–2005), free, no account needed. It has no date fields, so `policy_start_date`/`policy_end_date`/`loss_date` are derived deterministically from a hash of each row (documented in `claims_pipeline/transform.py` and `dbt/models/staging/stg_motor_claims.yml`) rather than being source truth. Synthetic claim narratives citing real PDS clauses are still a separate, unconfirmed task for the Advisor/Verifier flow.
- **DAG C transform/test tooling diverges from the rest of this plan on purpose.** The native-task design in `snowflake/02_dag.sql` (RAW→CLEAN→CURATED via Snowflake tasks) stays for the synthetic risk-scoring tables. DAG C instead uses **dbt** for its transforms and data-quality tests (`unique`/`not_null`/`accepted_values`/date-range/cross-field checks), orchestrated by a thin Airflow DAG (`dags/motor_claims_ingest.py`) whose actual daily run happens via **GitHub Actions** (`.github/workflows/motor-claims-daily.yml`, cron + manual dispatch), since Airflow doesn't run on the Windows dev laptop. Azure DevOps pipelines still own Power Platform solution ALM (Day 2 release pipeline) — this doesn't replace that, it's CI for one data pipeline.
- **Sparse vectors.** Snowflake's vector type is dense only, so store `indices` and `values` arrays. Qdrant is the open-source index (Pinecone is hosted).

## Environment status (as of 2026-10-28)

- **Student Azure subscription (UTS tenant): not usable for the OpenAI model.** A system-managed policy ("Allowed resource deployment regions", assignment id starts with `sys.`) limits regions to malaysiawest, japaneast, indonesiacentral, australiaeast and koreacentral and cannot be edited. GPT-4o-mini Standard quota exists only in East US 2 and Sweden Central (200K TPM), both blocked. Global Standard rows were not checked.
- **Personal Azure free account: now the main platform.** Created, signed in with `az login` (browser, broker disabled). Resource providers registered and `rg-claims-poc` created in australiaeast by `scripts/connect-personal.ps1`. Still to do: set a $50 budget alert, check GPT-4o-mini Standard quota in ai.azure.com, deploy it (name `claims-llm`).
- **Power Platform: not connected.** A personal Microsoft account is rejected ("not supported unless invited to an organization"). Plan: create a Microsoft Entra user in the personal Default Directory tenant (Global Administrator, throwaway tenant), sign in at make.powerapps.com with it, request the free Developer Plan, then `pac auth create --name personal --deviceCode --tenant <tenant-id>`. Eligibility is unconfirmed.
- **Snowflake: not set up.** Needs a trial account, then run `snowflake/00_bootstrap.sql` with a freshly generated key pair.
- **Work laptop is blocked by group policy** for Microsoft account sign-in. Continue on the personal laptop. Do not use the employer or university accounts for this project.
- **Quirk on the work laptop:** `az` printed nothing when called directly in PowerShell. Scripts call it through `cmd /c`. Probably not needed on the personal laptop.

## Existing files and what to change

- `snowflake/00_bootstrap.sql`: role, warehouse with a resource monitor, database, schemas, service user. Still valid.
- `snowflake/01_tables_and_seed.sql` and `snowflake/02_dag.sql`: written for the earlier risk-scoring design. **Rewrite** to the new design: PDS chunk and sparse vector tables, decisions, verifications and report tables, keep the RAW to CLEAN to CURATED task DAG and the claims sync view.
- `snowflake/03_motor_claims_raw.sql`: **new**, DAG C's `RAW.MOTOR_CLAIMS_RAW` table. Deliberately separate from `RAW.CLAIMS_RAW`/`CURATED.CLAIM_RISK` so the two pipelines don't collide.
- `claims_pipeline/`: **new** package — extract (CRAN `dataCar` tarball) → transform (derive keys/dates, sort, cap at 100,000) → load (Snowflake MERGE). `python -m claims_pipeline run [--dry-run]`.
- `dags/motor_claims_ingest.py`: **new**, thin Airflow DAG wrapping `claims_pipeline`.
- `dbt/`: **new** dbt project — `stg_motor_claims` / `fct_motor_claims` models plus schema and singular tests (uniqueness, date validity, claim/amount consistency, row-cap guard).
- `.github/workflows/motor-claims-daily.yml`: **new**, daily cron (+ manual dispatch) GitHub Actions run of the pipeline and `dbt build`.
- `scripts/check-access.ps1`: read-only connectivity checks (Azure, pac, Snowflake).
- `scripts/connect-personal.ps1`: signs in to the personal Azure subscription and Power Platform.
- `scripts/check_snowflake.py`: Snowflake connectivity test, reads env vars. Its key-pair auth block is the one reused in `claims_pipeline/config.py` — don't write a second auth path.
- `INIT.md`: setup notes, needs a refresh after this handoff.

## Schedule

### Before day 1 (blocking)
- [ ] Personal laptop: install Git, Python, Azure CLI, Power Platform CLI, Docker Desktop, VS Code, Claude Code.
- [ ] Azure budget alert at $50. Confirm GPT-4o-mini Standard quota and deploy `claims-llm`.
- [ ] Entra user, Power Apps Developer Plan, Copilot Studio trial, `pac auth` working.
- [ ] Snowflake trial account, bootstrap run, `check_snowflake.py` passes.
- [ ] `scripts/check-access.ps1` shows all PASS.

### Day 1: data, backend, security, pipeline
- [ ] Rewrite Snowflake scripts, load synthetic claims and the PDS.
- [x] DAG C: `dataCar` → Snowflake RAW, dbt transforms/tests, GitHub Actions daily run. Built on `feat/motor-claims-dag`.
- [ ] Airflow in Docker, DAGs A and B, Qdrant, fastembed.
- [ ] Agent API: Advisor and Verifier working from the command line.
- [ ] Key Vault, managed identity, Entra app registration for Dataverse.
- [ ] First CI pipeline.

### Day 2: Power Platform, release, governance
- [ ] Dataverse tables, DAG D sync, security roles.
- [ ] Power Automate flows, Copilot Studio agent, canvas app (test the chat embed first), model-driven app.
- [ ] Release pipeline for the solution.
- [ ] Governance docs: DLP, responsible-AI checklist, threat model, runbook, ADRs, record of the region-policy exception.
- [ ] End-to-end demo.

## Cost and safety rules

- Personal Azure free trial credit only. $50 budget alert. Deallocate the VM at the end of each session, Container Apps min replicas 0, Snowflake XSMALL with auto-suspend and a resource monitor.
- Standard deployment type for the model, never provisioned throughput (billed hourly when idle).
- Synthetic data only. No secrets in the repo.
- Delete `rg-claims-poc` and the service principal when the demo is over.

## Open questions

- ~~Which public source feeds DAG C, if any?~~ Answered: `dataCar` (CRAN `insuranceData`). See "Decisions made" above.
- Does the Developer Plan work for the Entra user in the personal tenant?
- Does the Copilot Studio chat embed in a canvas app in this tenant?
- Is Global Standard quota available for GPT-4o-mini on the personal subscription, or only Standard in East US 2 and Sweden Central?
