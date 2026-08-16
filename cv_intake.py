#!/usr/bin/env python3
"""cv_intake: extract text from a PDF resume and turn it into cv.md via an
LLM.
"""
from llm_providers import LLMError, gemini_generate

CV_PROMPT_TEMPLATE = """You are converting a resume into clean Markdown for a job-search \
tracking tool. Below is text extracted from a PDF resume (extraction may have \
mangled spacing/line breaks - use your judgment to reconstruct sensible content).

Output ONLY the markdown CV, structured with headings: # Name, ## Summary, \
## Experience, ## Education, ## Skills (adjust section names/order to fit what's \
actually in the source). Under Experience, use a heading per role with company, \
title, dates, then bullet points for accomplishments. Do not invent facts, \
numbers, or claims not present in the source text - if a section has nothing \
in the source, omit it rather than filling it with placeholders.

--- RESUME TEXT ---
{text}
--- END RESUME TEXT ---
"""


def extract_pdf_text(pdf_path):
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()


def build_cv_markdown(resume_text, api_key, model=None):
    if not resume_text.strip():
        raise LLMError("No extractable text found in that PDF (it may be a scanned "
                        "image without a text layer).")
    prompt = CV_PROMPT_TEMPLATE.format(text=resume_text[:20000])
    return gemini_generate(prompt, api_key, model=model)
