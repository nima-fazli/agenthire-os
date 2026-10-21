"""Pure tools bound to an authorized snapshot; models never supply tenant IDs."""

import hashlib
import json
import re

from pydantic import ValidationError

from app.core.quote_context import lexical_terms
from app.schemas.agent_workspace import ReviewAction


class AgentFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def terms(query):
    return sorted(lexical_terms(query))[:12]


def negated(text):
    return bool(
        re.search(
            r"\b(?:no|not|never|without|lack(?:ing)?|haven't|haven’t|don't|don’t)\b|ندارم|نداشته|نکرده|بدون تجربه|فاقد تجربه|آشنا نیست",
            text,
            re.IGNORECASE,
        )
    )


def line_context(body, start, end):
    left = body.rfind("\n", 0, start) + 1
    right = body.find("\n", end)
    return body[left : len(body) if right < 0 else right]


def search_sources(sources, query):
    found = []
    for source in sources:
        body = source["text"]
        positions = sorted(
            {
                m.start()
                for term in terms(query)
                for m in re.finditer(
                    r"(?<![\w+#])" + re.escape(term) + r"(?![\w+#])",
                    body,
                    re.IGNORECASE,
                )
            }
        )
        covered = -1
        for pos in positions:
            if pos < covered:
                continue
            start = max(body.rfind("\n", 0, pos) + 1, pos - 220)
            right = body.find("\n", pos)
            end = min(len(body) if right < 0 else right, start + 650)
            if end <= pos:
                end = min(len(body), pos + 200)
            found.append(
                {
                    "source_id": source["id"],
                    "start": start,
                    "end": end,
                    "quote": body[start:end],
                    "source_sha256": digest(body),
                    "negation_hint": negated(line_context(body, start, end)),
                }
            )
            covered = end
            if len(found) == 5:
                return found
    return found


def register_evidence(hit, witnesses):
    existing = next(
        (
            w
            for w in witnesses
            if all(w[k] == hit[k] for k in ("source_id", "start", "end", "quote"))
        ),
        None,
    )
    if existing:
        return dict(existing)
    item = {**hit, "evidence_id": f"e{len(witnesses) + 1}"}
    witnesses.append(item)
    return item


def validate_review(arguments, snapshot, witnesses):
    try:
        action = ReviewAction.model_validate(arguments)
    except ValidationError:
        raise AgentFailure("REVIEW_SCHEMA_INVALID") from None
    criteria = {c["key"]: c for c in snapshot["criteria"]}
    if set(action.findings) != set(criteria):
        raise AgentFailure("REVIEW_CRITERIA_INCOMPLETE")
    registry = {w["evidence_id"]: w for w in witnesses}
    sources = {s["id"]: s["text"] for s in snapshot["sources"]}
    findings, unclear = [], []
    for key, finding in action.findings.items():
        citations = []
        if finding.assessment == "supported" and not finding.evidence_ids:
            raise AgentFailure("EVIDENCE_REQUIRED")
        for eid in finding.evidence_ids:
            if eid not in registry:
                raise AgentFailure("EVIDENCE_ID_UNKNOWN")
            cite = registry[eid]
            body = sources.get(cite["source_id"], "")
            if (
                not 0 <= cite["start"] < cite["end"] <= len(body)
                or body[cite["start"] : cite["end"]] != cite["quote"]
            ):
                raise AgentFailure("QUOTE_MISMATCH")
            if finding.assessment == "supported":
                if negated(line_context(body, cite["start"], cite["end"])):
                    raise AgentFailure("NEGATED_EVIDENCE")
                if not set(terms(criteria[key]["query_text"])) & lexical_terms(
                    cite["quote"]
                ):
                    raise AgentFailure("QUOTE_NOT_RELEVANT")
            citations.append(
                {k: cite[k] for k in ("source_id", "start", "end", "quote")}
            )
        findings.append(
            {
                "key": key,
                "label": criteria[key]["label"],
                "assessment": finding.assessment,
                "citations": citations,
            }
        )
        if finding.assessment == "unclear":
            unclear.append(key)
    labels = [criteria[k]["label"] for k in unclear[:5]]
    return {
        "summary": f"Source excerpts identified for {len(criteria) - len(unclear)} of {len(criteria)} criteria. Criteria needing clarification: {len(unclear)}.",
        "findings": findings,
        "question_keys": unclear[:5],
        "question": "Please describe your practical experience with "
        + ", ".join(labels)
        + ". Include a project example and your responsibilities."
        if labels
        else None,
        "notice": "Quoted evidence supports human review; it does not verify skill or make a hiring decision.",
    }


def function(name, description, properties=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


def tool_definitions(kind, snapshot, state):
    read = state.get("read", [])
    if kind == "applicant":
        tools = [
            function(
                "get_public_job", "Read the explicitly published job description."
            ),
            function("get_my_application", "Read only this applicant's public status."),
            function(
                "get_requested_information",
                "Read the employer-approved clarification question.",
            ),
        ]
        topics = ["handoff"] + [
            topic
            for tool, topic in [
                ("get_public_job", "job"),
                ("get_my_application", "status"),
                ("get_requested_information", "requested_information"),
            ]
            if tool in read
        ]
        return [t for t in tools if t["function"]["name"] not in read] + [
            function(
                "respond_to_applicant",
                "Finish with facts already read; handoff for unavailable/private information.",
                {"topic": {"type": "string", "enum": topics}},
                ["topic"],
            )
        ]
    if "get_job" not in read:
        return [function("get_job", "Read the saved job criteria before starting.")]
    searched = {q.casefold().strip() for q in state.get("searched", [])}
    pending = [
        c["query_text"]
        for c in snapshot["criteria"]
        if c["query_text"].casefold().strip() not in searched
    ]
    query = {"type": "string", "minLength": 1, "maxLength": 256}
    if pending:
        query["enum"] = pending
    tools = [
        function(
            "search_resume",
            "Search this application's resume and answers. First cover every criterion; refine after coverage.",
            {"query": query},
            ["query"],
        )
    ]
    witnesses = state.get("witnessed", [])
    if witnesses:
        tools.append(
            function(
                "read_source",
                "Read additional source context, at most 700 Unicode characters.",
                {
                    "source_id": {
                        "type": "string",
                        "enum": list({w["source_id"] for w in witnesses}),
                    },
                    "start": {"type": "integer", "minimum": 0},
                    "end": {"type": "integer", "minimum": 1},
                },
                ["source_id", "start", "end"],
            )
        )
    if not pending:
        item = {
            "type": "object",
            "properties": {
                "assessment": {"type": "string", "enum": ["supported", "unclear"]},
                "evidence_ids": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "string",
                        "enum": [w["evidence_id"] for w in witnesses],
                    },
                },
            },
            "required": ["assessment", "evidence_ids"],
            "additionalProperties": False,
        }
        if not witnesses:
            item["properties"]["evidence_ids"]["maxItems"] = 0
            item["properties"]["evidence_ids"]["items"].pop("enum")
        keys = [c["key"] for c in snapshot["criteria"]]
        tools.append(
            function(
                "submit_review",
                "Finish the review. Use an object keyed by every criterion exactly once. Choose witnessed evidence IDs. Negated/missing/ambiguous experience is unclear. Server derives questions only for unclear criteria.",
                {
                    "findings": {
                        "type": "object",
                        "properties": {k: item for k in keys},
                        "required": keys,
                        "additionalProperties": False,
                    }
                },
                ["findings"],
            )
        )
    return tools


def execute_tool(kind, name, arguments, snapshot, state):
    definitions = {
        t["function"]["name"]: t["function"]
        for t in tool_definitions(kind, snapshot, state)
    }
    if name not in definitions:
        raise AgentFailure("TOOL_NOT_ALLOWED")
    schema = definitions[name]["parameters"]
    if not isinstance(arguments, dict) or set(arguments) != set(schema["required"]):
        raise AgentFailure("TOOL_ARGUMENTS_INVALID")
    read, witnesses, searched = (
        list(state.get("read", [])),
        list(state.get("witnessed", [])),
        list(state.get("searched", [])),
    )
    report = None
    if name == "get_job":
        result = {"title": snapshot["job_title"], "criteria": snapshot["criteria"]}
    elif name == "search_resume":
        query = arguments["query"]
        if not isinstance(query, str) or not 1 <= len(query) <= 256:
            raise AgentFailure("TOOL_ARGUMENTS_INVALID")
        if query.casefold().strip() in {q.casefold().strip() for q in searched}:
            raise AgentFailure("QUERY_ALREADY_SEARCHED")
        result = [
            register_evidence(hit, witnesses)
            for hit in search_sources(snapshot["sources"], query)
        ]
        searched.append(query)
    elif name == "read_source":
        source = next(
            (s for s in snapshot["sources"] if s["id"] == arguments["source_id"]), None
        )
        start, end = arguments["start"], arguments["end"]
        if (
            source is None
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(source["text"])
            or end - start > 700
        ):
            raise AgentFailure("TOOL_ARGUMENTS_INVALID")
        result = register_evidence(
            {
                "source_id": source["id"],
                "start": start,
                "end": end,
                "quote": source["text"][start:end],
                "negation_hint": negated(line_context(source["text"], start, end)),
            },
            witnesses,
        )
    elif name == "submit_review":
        report = validate_review(arguments, snapshot, witnesses)
        result = {"review": "validated", "next": "human_approval"}
    elif name == "respond_to_applicant":
        topic = arguments["topic"]
        if topic not in definitions[name]["parameters"]["properties"]["topic"]["enum"]:
            raise AgentFailure("READ_FACTS_FIRST")
        answer = {
            "job": snapshot["public_job"]["title"]
            + "\n"
            + snapshot["public_job"]["description"],
            "status": "Your application status: "
            + snapshot["public_status"]
            + ". The employer controls the next decision.",
            "requested_information": snapshot["public_question"]
            or "No additional information has been requested.",
            "handoff": "That information is not available in your applicant record. Please contact the employer.",
        }[topic]
        report = {"answer": answer, "topic": topic}
        result = {"response": "verified_public_facts"}
    else:
        result = {
            "get_public_job": snapshot.get("public_job"),
            "get_my_application": {"status": snapshot.get("public_status")},
            "get_requested_information": {"question": snapshot.get("public_question")},
        }[name]
    if name not in read:
        read.append(name)
    return result, {
        "read": read,
        "witnessed": witnesses,
        "searched": searched,
        "report": report,
    }
