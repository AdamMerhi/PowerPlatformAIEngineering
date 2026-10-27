# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

PowerPlatformAIEngineering — a proof of concept (POC) for applying AI engineering to the Microsoft Power Platform (Power Automate, Power Apps, Dataverse, Copilot Studio).

See `INIT.md` for setup and `PLAN.md` for the roadmap and current status.

## POC focus

Build "Claims PDS Agent" in 2 days: an agentic chat that reads new insurance claims, summarises them against the Product Disclosure Statement (PDS), recommends accept or decline with the cited clause, then re-checks every submitted decision against the PDS and reports on the whole claims log. A person decides every claim. It must cover: Power Apps (canvas and model-driven), Copilot Studio (the only chat interface, embedded in the canvas app), Dataverse, Azure OpenAI, Azure AI services, Azure AI Foundry, Power Platform and Azure integration, security by design, Azure DevOps CI/CD, governance, Airflow, and Snowflake holding sparse (fastembed) embeddings searched through Qdrant, plus a Snowflake DAG synced to Dataverse via REST API and OAuth. Use synthetic data only.

The architecture, decisions, environment status, schedule and open questions are in `PLAN.md`. Read it before doing anything.

## Working notes

- The owner is on a personal laptop. Do not use the employer (work) or university accounts for this project.
- Azure is the personal free-trial subscription, resource group `rg-claims-poc`, region `australiaeast`. Keep spend within the $50 budget. The student subscription is blocked by a region policy and is not used.
- Never ask for or store secrets in chat or in the repo. Credentials come from `az login`, `pac auth`, environment variables or `.env` (git-ignored).
- Visual Power Platform work (canvas app screens, Copilot Studio agent, connector sign-ins) is done by the owner in the portals. Write Dataverse schemas, Power Fx, flow definitions, DAGs, the Agent API, pipelines and docs.
- Commit and push only when asked. Create a branch rather than committing to `main`.

## Role context

The POC is framed around the **Intelligent Automation Engineer** position (Zurich, Australia/APAC; reports to Chapter Lead – Intelligent Automation Engineering; DT0000000098). Work should reflect what the role does:

- **Responsibilities:** design, build and deploy on Power Platform (Power Apps, Power Automate, Copilot Studio, Dataverse); embed AI via Azure OpenAI, Azure Cognitive Services and Azure AI Studio; integrate with Snowflake, SQL, Azure services, CRM/ERP and REST APIs; support existing automations (monitoring, incidents, tuning); write designs, runbooks and support guides; contribute reusable components and guardrails for citizen developers.
- **Engineering expectations:** secure-by-design, ALM and CI/CD with Azure DevOps and Git, modular and reusable design, error handling, logging, testing, responsible AI and governance.
- **Supporting tech:** REST, JSON, OAuth, Azure Functions, Logic Apps, Key Vault, messaging services.
- **Ways of working:** Agile squads (Scrum/Kanban); turn business requirements into user stories and technical designs.
- **Out of scope:** defining overall strategy. The role is operational delivery within established governance and architectural guardrails.

## Conventions

- Keep solution exports (unpacked) in source control; never commit packed `.zip` / `.msapp` artifacts.
- Never commit secrets, connection strings, tenant IDs, or environment URLs. Use `.env` (git-ignored) for local values.
- Prefer small, focused commits with descriptive messages.
- Update `PLAN.md` when scope or status changes.

## Commands

_To be filled in as tooling is added (e.g. `pac` CLI commands for solution export/import)._
