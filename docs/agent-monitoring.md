# Tracking the Claims PDS Agent

Everything below is in the personal subscription, resource group `rg-claims-poc`, region australiaeast. Nothing here
costs extra to look at.

## 1. Is it up, and how busy? (Azure portal)

portal.azure.com, then **Resource groups, rg-claims-poc, claims-agent** (Container App).

| Where | What you see |
|---|---|
| **Overview** | The public URL, the active revision, running status |
| **Monitoring, Metrics** | Requests, Replica count (watch it return to **0** when idle), CPU, Memory, Restarts |
| **Monitoring, Log stream** | Live console output while you click around in the demo page |
| **Application, Revisions and replicas** | Every deploy as a revision, with traffic share and health |
| **Monitoring, Logs** | Log Analytics: run the queries in section 3 |

"Replica count" at 0 is what proves there is no idle compute cost.

## 2. What is the model doing, and what does it cost? (Azure OpenAI)

portal.azure.com, then **Resource groups, rg-claims-poc, powerapps-pds-resource, Monitoring, Metrics**.

Useful metrics: **Azure OpenAI Requests**, **Processed Inference Tokens** (add the Prompt and Completion splits),
**Azure OpenAI Requests by status code** (a rise in 429s means you are hitting the token rate limit).

The same resource in the Foundry portal (ai.azure.com, project `powerapps-pds`): **Models + endpoints** shows the
`powerapps-pds` deployment, its rate limit (tokens per minute) and the Playground for trying prompts by hand.

Cost: **Cost Management, Cost analysis**, scope `rg-claims-poc`, group by *Resource*. Container compute should stay
at or near zero; the Azure OpenAI line is the one to watch. Set the $50 budget alert here (**Budgets, Add**).

## 3. Every call, in Log Analytics

The API writes one line per event. In the Container App, **Monitoring, Logs**, paste a query:

```kusto
// Recent agent events
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "claims-agent" and Log_s startswith "event="
| project TimeGenerated, Log_s
| order by TimeGenerated desc
| take 100
```

```kusto
// Model calls with token use (cost driver) and latency
ContainerAppConsoleLogs_CL
| where Log_s startswith "event=llm"
| extend input = toint(extract("input_tokens=(\\d+)", 1, Log_s)),
         output = toint(extract("output_tokens=(\\d+)", 1, Log_s)),
         ms = toint(extract("ms=(\\d+)", 1, Log_s))
| summarize calls = count(), input_tokens = sum(input), output_tokens = sum(output), avg_seconds = avg(ms) / 1000
  by bin(TimeGenerated, 1h)
```

```kusto
// How often is a decision flagged for a line manager?
ContainerAppConsoleLogs_CL
| where Log_s startswith "event=verify "
| extend flagged = Log_s has "requires_manager=True"
| summarize checks = count(), flagged = countif(flagged) by bin(TimeGenerated, 1d)
```

```kusto
// Cache hit rate for assessments
ContainerAppConsoleLogs_CL
| where Log_s startswith "event=assess "
| summarize calls = count(), cached = countif(Log_s has "cached=True")
```

```kusto
// Scale to zero and restarts (system events)
ContainerAppSystemLogs_CL
| where ContainerAppName_s == "claims-agent"
| project TimeGenerated, Reason_s, Log_s
| order by TimeGenerated desc
| take 50
```

Log lines never contain claim facts or the text of a question: only an 8-character claim prefix, the outcome, the
clauses cited, counts and timings. Logs are free up to 5 GB a month.

## 4. The audit trail (Power Platform)

make.powerapps.com, environment **adam's Environment**, **Tables**:

| Table | One row per | Useful columns |
|---|---|---|
| **Claim Assessments** | assessment (cached per claim and PDS version) | Outcome, Headline, Summary, Clauses, PDS version, Model, Created On |
| **Decision Checks** | decision check | Decision, Agrees with PDS, Reason supported, **Requires line manager**, Correct outcome, Finding, Clauses |
| **Claim Notes** | note or status change | Type, Author, Note, Created On (includes "Email held / Email sent" if the email flow is on) |

Open a table and choose **Data** to browse rows. These tables are the record of what the agent said and when, tied
to a PDS version, so a past decision can be reviewed against the policy text that applied at the time.

## 5. The build and the image (GitHub)

- **Actions, Agent API**: lint, tests, image build, offline smoke test, push. A red run means the image was not published.
- **Your profile, Packages, claims-agent**: every published image, tagged by commit.

## 6. Demonstrating it

Open `https://<app url>/demo`, paste the API key, pick a sample claim and use the four panels. The Evidence table
under each answer is the retrieval: the clauses the model read, with a match bar. Open Log stream next to it and
each click shows up as an `event=` line.

## Not set up yet

There is no Application Insights or Foundry tracing, so there are no per-request traces or prompt/response capture
in a portal. The `event=` log lines plus the Dataverse audit tables cover the demo. Adding OpenTelemetry tracing to
Application Insights is the next step if you want span-level traces.
