---
name: issue-to-spec
description: >-
  Pulls a GitHub issue given by number, URL, or owner/repo#number, analyzes the
  requested change, and creates a draft specification in docs/specs based on
  ..\SPEC_TEMPLATE.md.
user-invocable: true
---

# GitHub issue to draft spec

You turn one GitHub issue into one implementation-ready draft spec.

## Input

The user must provide a GitHub issue reference, such as:

- `#123`
- `123`
- `owner/repo#123`
- `https://github.com/owner/repo/issues/123`

If no issue reference is provided, ask for exactly one issue reference before
continuing.

## Required behavior

1. Pull the issue from GitHub with `gh`.
2. Read `..\SPEC_TEMPLATE.md` relative to the repository root.
3. Analyze the issue title, body, labels, author, assignees, milestone, and
   comments.
4. Create a draft spec file under `docs\specs\`.
5. Keep the spec faithful to the issue. Do not invent product scope.

## Commands and paths

Run commands from the repository root. On Windows, use PowerShell paths.

1. Confirm GitHub access:
   ```powershell
   gh auth status
   ```
2. Resolve the current repository when the input is only `#123` or `123`:
   ```powershell
   gh repo view --json nameWithOwner --jq .nameWithOwner
   ```
3. Fetch the issue:
   ```powershell
   gh issue view <issue-ref> --json number,title,body,author,labels,assignees,milestone,comments,state,url
   ```
4. Read the template at:
   ```text
   ..\SPEC_TEMPLATE.md
   ```
5. Write the generated spec to:
   ```text
   docs\specs\<issue-number>-<slug>.md
   ```

If `..\SPEC_TEMPLATE.md` does not exist, stop and explain that the template is
missing. Do not silently use another template.

## Analysis rules

- Treat the issue as the source of truth.
- Extract explicit acceptance criteria from the issue body and comments.
- Convert vague requirements into clearly marked assumptions or open questions.
- Preserve constraints, non-goals, and out-of-scope notes from the issue.
- If the issue has conflicting comments, capture the conflict under
  `Open Questions` instead of choosing one silently.
- If the issue is too vague for implementation, still create a draft spec, but
  set unresolved items under `Open Questions` and keep status `Draft`.
- Reference the issue URL in `References`.

## Spec generation rules

Base the output on the headings and intent of `..\SPEC_TEMPLATE.md`.

Fill the template as follows:

- Title: use `# <Issue title> Specification`.
- Status: `Draft`.
- Owner: issue assignee names if present, otherwise the issue author.
- Created and Last Updated: today's date.
- Overview: concise summary of the problem and desired outcome.
- Goals: what the issue explicitly asks to accomplish.
- Non-Goals: out-of-scope work from the issue, plus reasonable exclusions needed
  to prevent scope creep.
- User Stories: one or more stories derived from the issue, each with concrete
  acceptance criteria.
- Technical Design: describe likely affected surfaces, interfaces, data model,
  API, and UI/UX. Use `None expected` when a section is not affected.
- Implementation Plan: small ordered phases with checkboxes.
- Testing Strategy: meaningful tests that would fail if the requested behavior
  regressed.
- Rollout Plan: safe merge/deploy notes, including backward compatibility.
- Metrics & Success Criteria: measurable success signals when possible.
- Dependencies: code, systems, people, issues, or decisions needed.
- Risks & Mitigations: include at least one row, even if risk is low.
- Open Questions: unresolved ambiguity from the issue.
- References: include the GitHub issue URL and relevant comments/docs.

Remove placeholder text from the template. Do not leave `[Feature Name]`,
`Goal 1`, `Criterion 1`, or similar template placeholders in the generated spec.

## File naming

Create a stable lowercase slug from the issue title:

- lowercase
- replace non-alphanumeric runs with `-`
- trim leading/trailing `-`
- keep the filename reasonably short

Use this format:

```text
docs\specs\<issue-number>-<slug>.md
```

If that file already exists, do not overwrite it without checking whether it is
the existing spec for the same issue. If it is the same issue, update it
surgically. If it appears unrelated, create a new filename with a short suffix.

## Quality bar

- Keep the spec implementation-ready, not just a summary.
- Mark uncertainty explicitly instead of hallucinating.
- Keep scope narrow and traceable to the issue.
- Include practical test expectations.
- Use GitHub-flavored Markdown.
- Do not modify application code.

## Final response

After creating the spec, report:

- the issue analyzed,
- the spec path created or updated,
- any open questions that block implementation.
