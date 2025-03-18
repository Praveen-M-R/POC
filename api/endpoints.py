from fastapi import APIRouter, UploadFile, File, Form, HTTPException,Depends
import shutil
import os
from fastapi import HTTPException
import logging
from fastapi.responses import JSONResponse
from services.summary import stream_summary
logger = logging.getLogger(__name__)
from fastapi.responses import StreamingResponse
from services.flashcards import FlashcardGeneratorChatGPT,FlashcardGeneratorMistral,FlashcardGeneratorGemini
from services.mcqs import MCQGeneratorGemini,MCQGeneratorMistral, MCQGeneratorChatGPT
from pydantic import BaseModel
import time
from typing import List, Dict
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
client = MongoClient(MONGO_URI)
db = client["school_database"]
users_collection = db["users"]
reports_collection = db["reports"]


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@router.post("/register/")
async def register(username: str = Form(...), password: str = Form(...)):
    """Registers a new user and stores it in MongoDB."""
    if get_user_by_username(username):
        raise HTTPException(status_code=400, detail="User already exists")
    
    hashed_password = hash_password(password)
    user = {"username": username, "password": hashed_password, "reports": []}
    result = users_collection.insert_one(user)
    
    return {"message": "User registered successfully", "user_id": str(result.inserted_id)}

@router.post("/login/")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticates user and returns a JWT token."""
    user = get_user_by_username(form_data.username)
    
    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    access_token = create_access_token(data={"sub": str(user["_id"])}, expires_delta=timedelta(minutes=30))
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me/")
async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Retrieves the logged-in user's data and refreshes token if expired."""
    decoded_data = decode_access_token(token)

    user = get_user_by_id(decoded_data["payload"].get("sub"))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    response_data = {"username": user["username"], "reports": user.get("reports", [])}

    if decoded_data["new_token"]:
        response_data["new_access_token"] = decoded_data["new_token"]

    return response_data

@router.put("/update-profile/")
async def update_profile(new_password: str = Form(None), token: str = Depends(oauth2_scheme)):
    """Updates the user's profile (currently only allows password change)."""
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = get_user_by_username(payload.get("sub"))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = {}
    if new_password:
        update_data["password"] = hash_password(new_password)

    users_collection.update_one({"_id": user["_id"]}, {"$set": update_data})
    return {"message": "Profile updated successfully"}


@router.post("/flashcards/")
async def generate_flashcards(files: List[UploadFile] = File(...),model: str = Form(...)):
    """Generates flashcards directly from uploaded files."""
    
    full_paths = []
    
    for file in files:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())
        full_paths.append(file_path)

    for path in full_paths:
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

    if model == "chatgpt":
        flashcard_generator = FlashcardGeneratorChatGPT()
    elif model == "gemini":
        flashcard_generator = FlashcardGeneratorGemini()
    elif model == "mistral":
        flashcard_generator = FlashcardGeneratorMistral()
    else:
        raise HTTPException(status_code=400, detail="Invalid model specified")

    flashcards = flashcard_generator.generate_flashcards(file_paths=full_paths)

    if isinstance(flashcards, list):
        return {"flashcards": flashcards}
    else:
        raise HTTPException(status_code=500, detail="Failed to generate flashcards")

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
    """Uploads a PDF, generates a report, saves it to MongoDB, and links it to the user."""
    try:
        pdf_data = await file.read()
        student_report = process_pdf(pdf_data)

        if isinstance(student_report, dict): 
            saved_report = save_student_report(student_report)

            # Link report to user
            decoded_data = decode_access_token(token)
            user_id = decoded_data["payload"].get("sub")
            if not user_id:
                raise HTTPException(status_code=401, detail="Unauthorized")

            users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"latest_report_id": saved_report["_id"]}}
            )

            return {"message": "Report generated and saved successfully", "data": saved_report}
        else:
            return {"message": "Failed to generate a structured report", "data": student_report}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/profile/")
async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Retrieves the logged-in user's data along with their latest report."""
    decoded_data = decode_access_token(token)
    user = get_user_by_id(decoded_data["payload"].get("sub"))
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Fetch the latest report if available
    latest_report = None
    if "latest_report_id" in user:
        latest_report = reports_collection.find_one({"_id": ObjectId(user["latest_report_id"])})
        if latest_report:
            latest_report["_id"] = str(latest_report["_id"])

    response_data = {
        "username": user["username"],
        "reports": user.get("reports", []),
        "latest_report": latest_report
    }

    if decoded_data["new_token"]:
        response_data["new_access_token"] = decoded_data["new_token"]

    return response_data
