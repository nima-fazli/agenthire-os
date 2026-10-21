# Local agents: architecture and tradeoffs

AgentHire has two bounded agent profiles. The recruiting profile reviews an
application against saved job criteria. The applicant profile answers from that
person's public application facts. Both use the same local model and runtime;
they are not independent services negotiating with one another.

## Product boundary

An applicant is an ordinary global user, not an organization member. Creating an
account does not create a company. Email ownership is verified before submission.
Employers explicitly publish a separate public job description. Internal criteria,
private reports, other applicants and organization membership are never exposed by
the applicant assistant.

The recruiting agent can propose clarification and findings. An employer approves
or dismisses them. Approval does not change the hiring stage. Hiring and rejection
remain existing staff actions, with a public status notification when they change.

| Profile | Available tools | Final output |
| --- | --- | --- |
| Recruiter | `get_job`, `search_resume`, `read_source`, `submit_review` | Validated findings, citations and a proposed clarification |
| Applicant | `get_public_job`, `get_my_application`, `get_requested_information`, `respond_to_applicant` | Server-rendered public facts or employer handoff |

Tools receive an already-scoped snapshot. Tool arguments cannot select a tenant,
applicant, email recipient, SQL statement, filesystem path or arbitrary URL. There
is no browser, shell, mail-sending or hire/reject tool.

## Decision loop and persistence

Ollama returns one JSON-schema-constrained action. The runtime executes it and
appends its bounded result to the next decision's context. LangGraph represents
this one-turn choose/act graph. The worker owns persistence rather than relying on
an in-memory graph or presenting a graph-library import as durable execution.

Each successful turn commits its checkpoint, event, token counters and next state
together. A PostgreSQL queue claim uses `FOR UPDATE SKIP LOCKED` and a lease token.
Before persisting model output, the worker checks the lease, cancellation, actor
permissions and source fingerprint again. An expired worker cannot overwrite a
new claimant. Cancellation during inference wins over a late model result.

An interrupted inference call may run again after the lease expires. Inference is
not exactly-once. No external action is performed inside a model turn. Tool events
are bounded inputs/results, not private chain-of-thought, and hosted tracing is
explicitly disabled even if a parent process enables it.

Default bounds are 16 tool turns, 24,000 reported tokens and 600 seconds of
accumulated inference time. A call is bounded to 120 seconds plus identity-check
overhead. The worker's default lease is 240 seconds. Context and provider response
sizes are bounded too. The final turn is checked against budgets before acceptance.

Live calls validate the local origin, disable redirects and proxy inheritance,
check the model digest before/after inference and reject a changed model between
checkpoints. Truncated, malformed or incompatible provider output fails explicitly.
Changing the runtime protocol invalidates old checkpoints instead of guessing how
to resume them. There is no silent fallback to replay.

## Evidence and approval

Search uses full-token matching over immutable resume text, extracted PDF text and
append-only answers. Each search is bounded to five excerpts. The agent must read
the job and search every saved criterion before finalizing. A model can inspect
additional context with `read_source` and select witnessed evidence handles.

The server resolves a handle to its original source, Unicode offsets, exact quote
and source digest. Every criterion must appear exactly once, supported findings
need evidence, and literal relevance/negation checks run before a report is saved.
Negation checks use the surrounding original line, so a narrow excerpt cannot
simply remove an English `No` or a Persian negative suffix from the check.

These checks establish source integrity and conservative literal support. They do
not prove that a sentence entails expertise, that a claim is true, or that the
applicant can do the job. Ambiguous wording, synonyms, long multi-claim lines,
sarcasm and scanned PDFs remain limitations. The UI presents the actual quotes so
the employer can judge them. No numerical hireability ranking is produced.

The server renders the short summary and clarification from validated findings.
Approval binds to a fingerprint of the current job, criteria revision, application
and sources. A stale report cannot be approved after its inputs change. An approved
question becomes visible in the applicant portal and is queued for local email.
Answering a particular approved revision is append-only and queues a fresh review;
retrying the same answer is idempotent. The original submitted resume stays fixed.

## Submission, files and email

Draft uploads are applicant-only, bounded to 5 MiB and validated as PDF containers.
The upload endpoint stores bytes on the draft, then finalization publishes the PDF
using the existing private storage service. Metadata, application, extraction job,
receipt, agent run and notifications commit together. Failed finalization cleans up
only a file whose lack of committed metadata is known; uncertain outcomes are left
to reconciliation. Submitted files cannot be replaced through the portal.

Text PDFs use the existing extraction worker. Review waits for extraction within a
bounded interval; failed extraction is explicit. OCR is not included. Plain text
resumes are also supported. Drafts expire after one day and verification codes have
expiry, resend throttles and an attempt limit. OTP digests are HMACs; temporary
email bodies are removed by the worker's cleanup.

Notifications are persistent and per-user. Email uses a transactional outbox with
unique logical action keys, a lease, bounded retries and stable Message-IDs. SMTP
delivery is **at-least-once**: a crash after acceptance but before the database
commit may deliver a duplicate. Mailpit captures local messages and is not a real
internet email service. Organization mail views/retries are scoped to their own
recent submissions and approved questions.

## Local operation and honest evaluation

`compose.agents.yaml` adds the agent worker and Mailpit without replacing existing
database/document volumes. Ollama is an optional `live-ai` profile. Dependency and
model downloads require internet; inference has no paid API requirement. The model
uses existing hardware, so runtime and memory still matter.

Replay is an explicit deterministic transport for product and recovery tests.
It has zero model tokens and cannot earn live quality acceptance. The recorded
public demo uses synthetic replay events and never makes a hiring decision.

The evaluation corpus covers a small set of fictional positive, missing, negated,
Persian, unrelated, injection, late-evidence and Unicode cases. Recruiter and
applicant profiles have separate reports. Reports include the actual model digest,
runtime hash, corpus completeness, tool errors, usage and timing. Subsets, replay,
partial failures and substituted replay transports cannot claim full live acceptance.
Passing this corpus is diagnostic evidence, not general hiring validity.

Schema `0018_local_agents` adds eight tables and scoped constraints. Stop
`agent-worker` before using the historical backup/recovery scripts, which predate
this service. The updater backs up changed source files and the PostgreSQL database;
that is not a backup of the document volume. Historical release receipts remain
historical and must not be presented as current deployment acceptance.
