import json
import re
from fastapi import HTTPException
from google import genai
from google.genai import types
from core.config import GEMINI_API_KEY
from core.prompts import REPORT_PROMPT

genai_client = genai.Client(api_key=GEMINI_API_KEY)

def extract_json(response_text):
    """Extract JSON content from Gemini API response."""
    try:
        json_match = re.search(r"```json\n(.*?)\n```", response_text, re.DOTALL)
        json_data = json_match.group(1).strip() if json_match else response_text.strip()
        return json.loads(json_data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON response from AI model")

def process_pdf(pdf_data):
    """Processes PDF, generates report via Gemini AI, and structures it."""
    pdf_part = types.Part.from_bytes(data=pdf_data, mime_type="application/pdf")

    response = genai_client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[pdf_part, REPORT_PROMPT],
    )
    report = extract_json(response.text)
    student_data = {
        "student_info": report["student_info"],
        "subject_performance": report["subject_performance"],
        "strengths": report["strengths"],
        "weaknesses": report["weaknesses"],
        "overall_performance_summary": report["overall_performance_summary"],
    }
    if not student_data:
        return response.text
    return student_data
