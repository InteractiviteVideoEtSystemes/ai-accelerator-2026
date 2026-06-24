# ADR-0004: Use Claude Sonnet 4.6 via Azure for FR→EN document summarization

**Status:** Accepted
**Date:** 2026-06-24
**Deciders:** @bastien-martin

**Technical Story:** docs/specs/ai-document-summarization.md

## Context

The summarization feature must read French text and produce a faithful English
summary. The user explicitly requested the **Claude** model. We need an LLM
provider that the worker can call from an activity, configured via a secret, and a
model tier that balances summary quality with cost/latency. The deployment target
is Azure, so keeping the LLM traffic within the Azure boundary (rather than calling
Anthropic directly or via AWS Bedrock) is preferred for governance and billing
consolidation.

## Decision

We use **Claude Sonnet 4.6 accessed via Azure** (an Azure-hosted Claude endpoint),
called from the `summarize_with_claude` Temporal activity. The endpoint,
deployment name, and key are configuration (`AZURE_AI_INFERENCE_ENDPOINT`,
`AZURE_AI_SUMMARY_DEPLOYMENT`, `AZURE_AI_API_KEY`); the key is a secret sourced from
env/`.env` locally and a Kubernetes secret in-cluster — never committed and never
sent to the client bundle. **Sonnet 4.6** is chosen as the model tier for its
stronger reasoning/translation quality on summarization workloads, and it matches
the already-verified Azure AI Foundry deployment (`claude-sonnet-4-6`).

## Consequences

### Positive
- Meets the explicit requirement to use Claude; Sonnet 4.6 gives higher-quality,
  more faithful FR→EN summaries than a smaller tier.
- Reuses the already-provisioned, verified `claude-sonnet-4-6` Azure deployment —
  no new model deployment to stand up.
- Traffic stays within the Azure boundary, aligning with the deployment target
  (ADR-0001/0002) and simplifying governance/billing.

### Negative
- Dependency on a billable Azure-hosted model with rate limits and outage risk
  (mitigated by the Temporal retry policy — see ADR-0003).
- Higher per-token cost and latency than a Haiku-class tier; mitigated by the
  512 KB input cap and chunk/map-reduce above 128 KB.
- Sending document text to a managed model service raises data-handling
  considerations; mitigated by redacting personal names before the call.

### Neutral
- The activity contract is provider-agnostic, so the exact Azure deployment
  name/version can change without code changes (`AZURE_AI_SUMMARY_DEPLOYMENT`).

## Options Considered

### Option 1: Claude Sonnet 4.6 via Azure-hosted endpoint (chosen)
- **Pros:** satisfies the Claude requirement; keeps traffic in the Azure boundary;
  Sonnet 4.6 maximizes summary quality and reuses the verified deployment.
- **Cons:** higher cost/latency than Haiku; depends on Azure Claude availability.

### Option 2: Claude Haiku via Azure-hosted endpoint
- **Pros:** lowest cost/latency on the Azure boundary.
- **Cons:** weaker translation/summarization quality; a Haiku deployment is not
  currently provisioned/verified in the target Foundry project.

### Option 3: Anthropic Claude via the direct API
- **Pros:** fewer moving parts; latest models first.
- **Cons:** external egress; data leaves the Azure boundary; separate billing.

### Option 4: Claude via Amazon Bedrock
- **Pros:** managed boundary on AWS.
- **Cons:** cross-cloud (AWS) while the stack targets Azure.

### Option 5: A different provider (e.g. Azure OpenAI)
- **Pros:** native Azure option.
- **Cons:** contradicts the explicit request to use Claude.

## Quality & Security (Non-Negotiable)

- **Key is a secret, always.** `AZURE_AI_API_KEY` lives only in env/`.env`
  (gitignored) and K8s secrets — never committed, never logged, never sent to the
  client bundle.
- **Redact before sending.** Personal names are stripped before any text reaches
  the model; the system prompt also instructs the model to omit personal names.
- **Traffic stays in the Azure boundary** (no direct third-party egress), aligning
  with the deployment governance model.
- **Mockable, offline-by-default tests.** The Azure-Claude client is mocked in unit
  tests; real calls are gated behind an env flag so CI is never billable.

## Related Decisions

- ADR-0003 (Temporal workflow orchestration that wraps this provider call).
- ADR-0005 (Supabase Edge Function entry point).

## Notes

Accepted per explicit user decision: **Claude Sonnet 4.6**, **via Azure**. The
deployment targets the verified Azure AI Foundry `claude-sonnet-4-6` model and is
configurable via `AZURE_AI_SUMMARY_DEPLOYMENT`. A `redact_personal_names` step
removes first names/surnames before any text is sent to the model or persisted.

### History

- 2026-06-24: Superseded the initial **Claude Haiku** model choice with **Claude
  Sonnet 4.6** (same provider, same Azure boundary, same activity contract) to
  prioritize summary quality and reuse the verified `claude-sonnet-4-6` deployment.
