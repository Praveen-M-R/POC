from fastapi import APIRouter, UploadFile, File, Form, HTTPException,Depends,Query
import shutil
import os
from fastapi import HTTPException
import logging
from fastapi.responses import JSONResponse
from services.summary import stream_summary
logger = logging.getLogger(__name__)
from fastapi.responses import StreamingResponse
from services.mcqs import MCQGeneratorGemini,MCQGeneratorMistral, MCQGeneratorChatGPT
from pydantic import BaseModel
import time
from typing import List, Dict, Optional
router = APIRouter()
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
from core.config import OPENAI_API_KEY
from openai import OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)
import json
from services.report import process_pdf,extract_json
from datastorage.db_connect import save_student_report
import re
from services.auth import hash_password, verify_password, create_access_token, decode_access_token, get_user_by_username
from datastorage.db_connect import users_collection
from datetime import timedelta
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from services.auth import get_user_by_id
from core.config import MONGO_URI
from pymongo import MongoClient
from bson import ObjectId
from fastapi import APIRouter, Form, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import timedelta
from datastorage.db_connect import users_collection, reports_collection
from services.auth import hash_password, verify_password, create_access_token, decode_access_token,get_user_by_username,get_user_by_id
from core.prompts import MCQ_PROMPT_WITH_REPORT,MCQ_PROMPT_WITHOUT_REPORT

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@router.post("/register/")
async def register(username: str = Form(...), password: str = Form(...)):
    """Registers a new user and stores it in Firestore."""
    if await get_user_by_username(username):
        raise HTTPException(status_code=400, detail="User already exists")
    
    hashed_password = hash_password(password)
    user_data = {"username": username, "password": hashed_password, "reports": []}
    
    user_ref = users_collection.add(user_data)
    return {"message": "User registered successfully", "user_id": user_ref[1].id}

@router.post("/login/")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticates user and returns a JWT token."""
    user = await get_user_by_username(form_data.username)
    
    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    access_token = create_access_token(data={"sub": user["id"]}, expires_delta=timedelta(minutes=30))
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/notes/")
async def generate_notes(files: list[UploadFile] = File(...), model: str = Form(...)):
    """Accept multiple PDFs, process them, and return structured notes."""
    
    file_paths = []
    for file in files:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())
        file_paths.append(file_path)

    return StreamingResponse(stream_summary(file_paths,model), media_type="text/event-stream")

class TopicSelection(BaseModel):
    topics: List[str]
    file_paths: List[str]
    model: str

class MCQResponse(BaseModel):
    topic: str
    question: str
    options: List[str]
    correct_answer: str

def get_mcq_generator(model: str):
    """Returns the appropriate MCQ generator class based on the selected model."""
    model_map = {
        "gemini": MCQGeneratorGemini,
        "mistral":MCQGeneratorMistral,
        "chatgpt":MCQGeneratorChatGPT,
    }
    if model not in model_map:
        raise HTTPException(status_code=400, detail="Invalid model specified")
    return model_map[model]()


@router.post("/mcqs/")
async def extract_topics(files: List[UploadFile] = File(...), model: str = Form(...)):
    """Extracts structured topics from uploaded PDFs using the selected AI model."""
    mcq_generator = get_mcq_generator(model)
    structured_topics = {}

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    full_paths = []
    for file in files:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())
        full_paths.append(file_path)
        
        extracted_topics = mcq_generator.upload_and_parse_file(file_path)
        structured_topics.update(extracted_topics)
    if not structured_topics:
        raise HTTPException(status_code=500, detail="❌ Failed to extract topics from files.")

    return {"topics": structured_topics,"file_paths": full_paths}

@router.post("/mcqs/generate/", response_model=List[MCQResponse])
async def generate_selected_mcqs(topic_selection: TopicSelection):
    """Generates MCQs for selected topics using the uploaded file and model."""
    if not topic_selection.topics:
        raise HTTPException(status_code=400, detail="No topics selected")
    mcq_generator = get_mcq_generator(topic_selection.model.lower())
    mcqs = mcq_generator.generate_mcqs(topic_selection.topics, topic_selection.file_paths)

    if not mcqs:
        raise HTTPException(status_code=500, detail="Failed to generate MCQs")

    mcqs = mcqs.strip()
    if mcqs.startswith("```json"):
        mcqs = mcqs[7:-3]

    try:
        mcq_data = json.loads(mcqs)
    except json.JSONDecodeError as e:
        print("❌ JSON Parsing Error:", e)
        print("Raw MCQ Response:", mcqs)
        raise HTTPException(status_code=500, detail="Failed to parse MCQs")

    formatted_mcqs = [
        {
            "topic": mcq["Topic"],
            "question": mcq["Question"],
            "options": mcq["Options"],
            "correct_answer": mcq["Correct Answer"]
        }
        for mcq in mcq_data
    ]

    return formatted_mcqs

def extract_json(response_text):
    """Extract JSON content from Gemini API response."""
    try:
        json_match = re.search(r"```json\n(.*?)\n```", response_text, re.DOTALL)
        json_data = json_match.group(1).strip() if json_match else response_text.strip()
        return json.loads(json_data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON response from AI model")

@router.post("/report/")
async def upload_and_generate_report(file: UploadFile = File(...)):
    """Uploads a PDF, generates a report, and saves it to MongoDB if valid."""
    try:
        pdf_data = await file.read()
        student_report = process_pdf(pdf_data)
        print(student_report)
        if isinstance(student_report, dict): 
            saved_report = save_student_report(student_report)
            return {"message": "Report generated and saved successfully", "data": saved_report}
        else:
            return {"message": "Failed to generate a structured report", "data": student_report}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/report-profile/")
async def upload_and_generate_report(file: UploadFile = File(...), token: str = Depends(oauth2_scheme)):
    """Uploads a PDF, generates a report, saves it to Firestore, and links it to the user."""
    try:
        pdf_data = await file.read()
        student_report = process_pdf(pdf_data)
        print(student_report)

        if not isinstance(student_report, dict):
            raise HTTPException(status_code=400, detail="Failed to generate a structured report")

        print("✅ Report successfully generated.")

        report_ref = reports_collection.add(student_report)
        doc_id = report_ref[1].id

        print("📌 Report saved to Firestore:", doc_id)

        decoded_data = decode_access_token(token)
        user_id = decoded_data["payload"].get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")

        user_ref = users_collection.document(user_id)
        user_ref.update({"latest_report_id": doc_id})

        return {
            "message": "Report generated and saved successfully",
            "data": {"_id": doc_id, **student_report},
        }

    except Exception as e:
        print("❌ Error in upload_and_generate_report:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/profile/")
async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Retrieves the logged-in user's data along with their latest report."""
    try:
        decoded_data = decode_access_token(token)
        user_id = decoded_data["payload"].get("sub")

        if not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")

        user_ref = users_collection.document(user_id).get()
        if not user_ref.exists:
            raise HTTPException(status_code=404, detail="User not found")

        user_data = user_ref.to_dict()
        latest_report = None

        if "latest_report_id" in user_data:
            report_ref = reports_collection.document(user_data["latest_report_id"]).get()
            if report_ref.exists:
                latest_report = report_ref.to_dict()
                latest_report["_id"] = user_data["latest_report_id"]

        return {
            "username": user_data["username"],
            "latest_report": latest_report
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class MCQRequest(BaseModel):
    model: str
    file_paths: List[str]

@router.post("/mcqs/personalized/", response_model=List[MCQResponse])
async def generate_personalized_mcqs(
    model: str = Form(...),
    files: List[UploadFile] = File(...),
    token: str = Depends(oauth2_scheme)
):
    try:
        decoded_data = decode_access_token(token)
        user_id = decoded_data["payload"].get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")

        user_ref = users_collection.document(user_id).get()
        if not user_ref.exists:
            raise HTTPException(status_code=404, detail="User not found")
        user_data = user_ref.to_dict()

        latest_report = None
        if "latest_report_id" in user_data:
            report_ref = reports_collection.document(user_data["latest_report_id"]).get()
            if report_ref.exists:
                latest_report = report_ref.to_dict()

        weak_areas = latest_report.get("weaknesses", []) if latest_report else []
        strong_areas = latest_report.get("strengths", []) if latest_report else []
        
        weak_subjects = [area["subject"] for area in weak_areas] if weak_areas else []
        strengths_formatted = ", ".join(strong_areas) if strong_areas else "None"
        weaknesses_formatted = ", ".join(weak_subjects) if weak_subjects else "None"
    
        prompt = MCQ_PROMPT_WITH_REPORT.format(
            strengths=strengths_formatted,
            weaknesses=weaknesses_formatted
        ) if strong_areas or weak_areas else MCQ_PROMPT_WITHOUT_REPORT
        mcq_generator = get_mcq_generator(model)
       
        full_paths = []
        for file in files:
            file_path = os.path.join(UPLOAD_DIR, file.filename)
            with open(file_path, "wb") as buffer:
                buffer.write(await file.read())
            full_paths.append(file_path)
        
        mcqs = mcq_generator.generate_personalized_mcqs(prompt,full_paths)

        if not mcqs:
            raise HTTPException(status_code=500, detail="Failed to generate MCQs")

        mcqs = mcqs.strip()
        if mcqs.startswith("```json"):
            mcqs = mcqs[7:-3]

        try:
            mcq_data = json.loads(mcqs)
        except json.JSONDecodeError as e:
            print("❌ JSON Parsing Error:", e)
            print("Raw MCQ Response:", mcqs)
            raise HTTPException(status_code=500, detail="Failed to parse MCQs")
        formatted_mcqs = [
            {
                "topic": mcq["Topic"],
                "question": mcq["Question"],
                "options": mcq["Options"],
                "correct_answer": mcq["Correct Answer"] 
            }
            for mcq in mcq_data
        ]

        return formatted_mcqs

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
