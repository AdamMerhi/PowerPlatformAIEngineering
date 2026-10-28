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
- **Power Platform:** canvas app with a custom chat screen (built in Power Fx, calling the Agent API via Power Automate) plus an approve/override card, model-driven app for the claims log and audit trail, Power Automate flows as agent tools, Dataverse. **Copilot Studio dropped** — the canvas app surfaces the AI directly instead of through a Copilot Studio agent, removing the embed step and the extra trial dependency.
- **Cross-cutting:** Azure DevOps pipelines, security by design, governance framework.

### Run order
1. DAG A: PDS PDF to Document Intelligence, chunk, fastembed sparse vectors, Snowflake.
2. DAG B: Snowflake vectors to Qdrant.
3. DAG C: public claims data into Snowflake RAW.
4. DAG D: CURATED to Dataverse (REST + Entra OAuth).
5. Adjuster asks the canvas app's chat screen for new claims. Power Automate calls the Agent API: Reader, Advisor (retrieve PDS clauses, Azure OpenAI summary and recommendation, PII redacted first, outputs safety-filtered).
6. Adjuster confirms or overrides. Decision saved to Dataverse and Snowflake with reason and clause IDs.
7. Verifier re-checks each decision against the PDS and flags unsupported declines.
8. Reporter builds the claims-log report.

## Decisions made

- **2-day slice, cheap stack.** Airflow in Docker Compose on one small VM (deallocate when idle), Qdrant embedded in the Agent API and rebuilt from Snowflake at start-up, Agent API on Container Apps scaled to zero, one chat model deployed (no embedding model, fastembed runs locally), free tiers for Language, Content Safety and Document Intelligence. No AKS.
- **Orchestration.** LangChain (owner's choice) drives the Reader, Advisor, Verifier and Reporter chains against the Azure OpenAI deployment `powerapps-pds`. Retrieval is sparse (fastembed) through Qdrant, over PDS chunks stored in Snowflake.
- **Use case and PDS.** Zurich Business Insurance Motor PDS (public PDF: https://www.zurich.com.au/-/media-assets/project/zurich-headless/shared/content/dam/au-documents/business-insurance/motor/motor-insurance-pds.pdf). The ASIC case (25-077MR) is the motivating story — a wrong decline found by QA — but the demo claims are synthetic motor claims, which is accepted even though the real case concerned trauma cover. The PDS is a public document; claims stay synthetic. **Update:** the PDS the demo actually uses is now the synthetic Outback Ute Cover PDS (`docs/pds/ute-cover-pds.md`), because its numbered clauses map directly onto the `dataCar` columns and give a checkable accept/refer/decline outcome (`CURATED.V_CLAIM_ASSESSMENT`). The Zurich PDF remains the motivating reference only.
- **Front end.** Canvas app builds its own chat screen (gallery + text input, Power Fx calling a Power Automate flow) instead of embedding a Copilot Studio agent. Dropped Copilot Studio to remove the embed-compatibility risk and the extra trial/app dependency, now that Azure AI Foundry and Power Platform cover the AI and front-end surfaces directly.
- **Public claims data.** DAG C's source is settled: `dataCar` from the CRAN R package `insuranceData` — 67,856 real Australian third-party motor policies (2004–2005), free, no account needed. It has no date fields, so `policy_start_date`/`policy_end_date`/`loss_date` are derived deterministically from a hash of each row (documented in `claims_pipeline/transform.py` and `dbt/models/staging/stg_motor_claims.yml`) rather than being source truth. Synthetic claim narratives citing real PDS clauses are still a separate, unconfirmed task for the Advisor/Verifier flow.
- **DAG C transform/test tooling diverges from the rest of this plan on purpose.** The native-task design in `snowflake/02_dag.sql` (RAW→CLEAN→CURATED via Snowflake tasks) stays for the synthetic risk-scoring tables. DAG C instead uses **dbt** for its transforms and data-quality tests (`unique`/`not_null`/`accepted_values`/date-range/cross-field checks), orchestrated by a thin Airflow DAG (`dags/motor_claims_ingest.py`) whose actual daily run happens via **GitHub Actions** (`.github/workflows/motor-claims-daily.yml`, cron + manual dispatch), since Airflow doesn't run on the Windows dev laptop. Azure DevOps pipelines still own Power Platform solution ALM (Day 2 release pipeline) — this doesn't replace that, it's CI for one data pipeline.
- **Sparse vectors.** Snowflake's vector type is dense only, so store `indices` and `values` arrays. Qdrant is the open-source index (Pinecone is hosted).

## Environment status (as of 2026-10-28)

- **Student Azure subscription (UTS tenant): not usable for the OpenAI model.** A system-managed policy ("Allowed resource deployment regions", assignment id starts with `sys.`) limits regions to malaysiawest, japaneast, indonesiacentral, australiaeast and koreacentral and cannot be edited. GPT-4o-mini Standard quota exists only in East US 2 and Sweden Central (200K TPM), both blocked. Global Standard rows were not checked.
- **Personal Azure free account: connected, model not yet deployed.** Tenant `doubleyouthotmail.onmicrosoft.com` (ID `0232ac94-3ce5-4a76-8035-faf67c0758d0`), subscription "Azure subscription 1" (`29386ebe-c2d8-4545-ba09-2e6e59973e34`), signed in as `amerhi@doubleyouthotmail.onmicrosoft.com` via `az login`. Resource providers registered and `rg-claims-poc` created in australiaeast by `scripts/connect-personal.ps1`; `gpt-4o-mini` confirmed listed in australiaeast. **Blocked:** ai.azure.com reports "You don't have permission to create resources in any subscription" when creating a project — role assignment on the subscription needs checking (see open questions). Still to do: set a $50 budget alert, resolve the permission error, deploy the model (name `claims-llm`).
- **Power Platform: connected, Dataverse environment provisioned.** The tenant's Default environment (`Default-0232ac94-3ce5-4a76-8035-faf67c0758d0`) has no Dataverse database. Signed up for the free Developer Plan as `amerhi@doubleyouthotmail.onmicrosoft.com`, which provisioned a dedicated environment ("adam's Environment", ID `de914c81-ca32-e9ec-97a7-0f3c13c6c1c4`, instance URL `https://orgbe1ca320.crm6.dynamics.com/`, org ID `16e86f7c-77d2-f111-a42d-002248964acd`). `pac auth create --environment https://orgbe1ca320.crm6.dynamics.com/` and `pac org who` both succeed.
- **Snowflake: connected.** Trial account `koztrrz-vx72782` (AU). Key pair already generated at `keys/poc_svc.p8` / `keys/poc_svc.pub` (git-ignored) and the public key is baked into `snowflake/00_bootstrap.sql`. Bootstrap script run as `ACCOUNTADMIN`; `.env` filled in with `SNOWFLAKE_ACCOUNT=koztrrz-vx72782` and the key path. `scripts/check_snowflake.py` connects successfully.
- **`scripts/check-access.ps1`:** all real connections (Azure, Dataverse, Snowflake) now PASS. The "Azure CLI installed" and "Power Platform CLI (pac)" rows previously showed FAIL even on success, because `az --version` / `pac help` can return a non-zero exit code on a clean run (update-nag warnings); the script now ignores exit code for just those two cosmetic checks.
- **Work laptop is blocked by group policy** for Microsoft account sign-in. Continue on the personal laptop. Do not use the employer or university accounts for this project.
- **Quirk on the work laptop:** `az` printed nothing when called directly in PowerShell. Scripts call it through `cmd /c`. Probably not needed on the personal laptop.

## Existing files and what to change

- `snowflake/00_bootstrap.sql`: role, warehouse with a resource monitor, database, schemas, service user. Still valid.
- `snowflake/01_tables_and_seed.sql` and `snowflake/02_dag.sql`: written for the earlier risk-scoring design. **Rewrite** to the new design: PDS chunk and sparse vector tables, decisions, verifications and report tables, keep the RAW to CLEAN to CURATED task DAG and the claims sync view.
- `snowflake/03_motor_claims_raw.sql`: **new**, DAG C's `RAW.MOTOR_CLAIMS_RAW` table. Deliberately separate from `RAW.CLAIMS_RAW`/`CURATED.CLAIM_RISK` so the two pipelines don't collide.
- `claims_pipeline/`: **new** package — extract (CRAN `dataCar` tarball) → transform (derive keys/dates, sort, cap at 100,000) → load (Snowflake MERGE). `python -m claims_pipeline run [--dry-run]`.
- `dags/motor_claims_ingest.py`: **new**, thin Airflow DAG wrapping `claims_pipeline`.
- `dbt/`: **new** dbt project — `stg_motor_claims` / `fct_motor_claims` models plus schema and singular tests (uniqueness, date validity, claim/amount consistency, row-cap guard).
- `docs/pds/ute-cover-pds.md`: **new**, synthetic "Outback Ute Cover" PDS. Numbered clauses (2.1 covered vehicles, 2.2 eligible drivers, 3.x policy period, 4.x amounts, 6.1 repeat claims) each name the claims column they are checked against. This is the document DAG A parses and embeds. Clause 2.2 (female drivers only) is a deliberate test rule, labelled as such in the text.
- `snowflake/04_claim_assessment.sql`: **new**, `CURATED.V_CLAIM_ASSESSMENT` applies the PDS rules deterministically to every claim (`recommended_outcome`, `cited_clauses`, `conditions`). The Advisor retrieves clause text by RAG and takes the outcome from here. The Verifier re-checks human decisions against it. Thresholds live in one `rules` CTE.
- `snowflake/05_claim_queue.sql`: **new**, `CURATED.V_CLAIM_QUEUE`, a deterministic 100-claim demo queue (25 ACCEPT, 25 REFER, 50 DECLINE). The real data is 97.4% DECLINE under these rules, so a random queue would not demo well.
- `.github/workflows/motor-claims-daily.yml`: **new**, daily cron (+ manual dispatch) GitHub Actions run of the pipeline and `dbt build`.
- `scripts/check-access.ps1`: read-only connectivity checks (Azure, pac, Snowflake).
- `scripts/connect-personal.ps1`: signs in to the personal Azure subscription and Power Platform.
- `scripts/check_snowflake.py`: Snowflake connectivity test, reads env vars. Its key-pair auth block is the one reused in `claims_pipeline/config.py` — don't write a second auth path.
- `INIT.md`: setup notes, needs a refresh after this handoff.

## Schedule

### Before day 1 (blocking)
- [ ] Personal laptop: install Git, Python, Azure CLI, Power Platform CLI, Docker Desktop, VS Code, Claude Code.
- [ ] Azure budget alert at $50. Confirm GPT-4o-mini Standard quota and deploy `claims-llm`.
- [ ] Entra user, Power Apps Developer Plan, `pac auth` working.
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
- [ ] Power Automate flows, canvas app chat screen (calling the Agent API), model-driven app.
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
- Is Global Standard quota available for GPT-4o-mini on the personal subscription, or only Standard in East US 2 and Sweden Central?
- Why does ai.azure.com say "You don't have permission to create resources in any subscription" for `amerhi@doubleyouthotmail.onmicrosoft.com`, who is the subscription owner? Check Access control (IAM) role assignment on the subscription in `portal.azure.com`, and confirm the AI Foundry UI has the correct directory/subscription selected (not a cached second account).
