import hashlib
import json
from pathlib import Path

from app.schemas.retrieval_evaluation import EvaluationObservations, EvaluationSuite
from scripts.candidate_document_smoke import sample_pdf
from scripts.evaluation_report import read_json
from scripts.job_matching_smoke import split_skills_pdf

FIXTURES = Path(__file__).parent / "fixtures"
SUITE_PATH = FIXTURES / "retrieval_evaluation_v1.json"
EXAMPLE_PATH = FIXTURES / "retrieval_observations_example.json"
PERSIAN_SOURCE = "كَيَان مهندس\u200cنرم\u200cافزار"
RESUME_TEXT = {
    "ada": "Python SQL backend APIs Python SQL",
    "grace": "Python Django testing Python",
    "linus": "Java SQL systems SQL",
    "pending": "Rust Python SQL",
    "other-tenant": "Python SQL backend APIs Python SQL",
}
ITEM_KEYS = (
    "ada",
    "grace",
    "linus",
    "bruno",
    "kian",
    "empty",
    "pending",
    "other-tenant",
)


def load_suite() -> EvaluationSuite:
    suite = EvaluationSuite.model_validate(read_json(SUITE_PATH))
    if suite.corpus_sha256 != fixture_corpus_digest():
        raise ValueError("Reference corpus fingerprint no longer matches its fixtures.")
    return suite


def load_example() -> EvaluationObservations:
    return EvaluationObservations.model_validate(read_json(EXAMPLE_PATH))


def ascii_resume_pdf(text: str) -> bytes:
    if (
        not text.strip()
        or len(text) > 120
        or any(not 32 <= ord(char) < 127 for char in text)
    ):
        raise ValueError("PDF fixture text must be short printable ASCII.")
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 9 Tf 40 740 Td ({escaped}) Tj ET\n".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream",
    ]
    data, offsets = b"%PDF-1.7\n", []
    for number, value in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + value + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return (
        data
        + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )


def fixture_corpus_digest() -> str:
    documents = {}
    for key in ITEM_KEYS:
        values = []
        if key == "bruno":
            values = [(split_skills_pdf(), "indexed", None)]
        elif key == "kian":
            values = [(sample_pdf(), "synthetic_index", PERSIAN_SOURCE)]
        elif key in RESUME_TEXT:
            pdf = ascii_resume_pdf(RESUME_TEXT[key])
            values = [(pdf, "pending" if key == "pending" else "indexed", None)]
            if key == "ada":
                values += [
                    (pdf + b"\n", "indexed", None),
                    (pdf + b"\n\n", "pending", None),
                ]
        documents[key] = [
            {
                "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
                "state": state,
                "synthetic_text_sha256": hashlib.sha256(source.encode()).hexdigest()
                if source
                else None,
            }
            for pdf, state, source in values
        ]
    canonical = json.dumps(documents, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
