from fastapi import APIRouter, UploadFile, File, Form, HTTPException
import shutil
import os
from fastapi import HTTPException
import logging
from fastapi.responses import JSONResponse
from services.summary import stream_summary
logger = logging.getLogger(__name__)
from fastapi.responses import StreamingResponse
from services.chat import DocumentChatServiceGemini,DocumentChatServiceOpenAI
from services.flashcards import FlashcardGeneratorChatGPT,FlashcardGeneratorMistral,FlashcardGeneratorGemini
from services.mcqs import MCQGeneratorGemini,MCQGeneratorMistral, MCQGeneratorChatGPT
from pydantic import BaseModel
import time
from typing import List, Dict
router = APIRouter()
chat_service = DocumentChatServiceGemini()
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
from core.config import OPENAI_API_KEY
from openai import OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)
import json

CHAT_SERVICES = {
    "gemini": DocumentChatServiceGemini(collection_name="document-chat-collection-gemini"),
    "chatgpt": DocumentChatServiceOpenAI(collection_name="document-chat-collection-openai")
}

@router.post("/upload/")
async def upload_document(file: UploadFile = File(...), model: str = Form("gemini")):
    """Uploads a document and stores it for later summarization with the selected model."""
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    if model not in CHAT_SERVICES:
        raise HTTPException(status_code=400, detail=f"Invalid model. Choose from {list(CHAT_SERVICES.keys())}")

    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        chat_service = CHAT_SERVICES[model]
        chat_service.load_pdf(file_path)
        logging.info(f"File '{file.filename}' saved successfully for model '{model}'.")
        return JSONResponse(
            status_code=200,
            content={"message": "File uploaded successfully", "file_path": file_path, "model": model}
        )
    except Exception as e:
        logging.error(f"Error uploading file for model '{model}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ask/")
async def ask_question(query: str = Form(...), model: str = Form("gemini")):
    """Asks a question about the uploaded document using the selected model."""
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    
    if model not in CHAT_SERVICES:
        raise HTTPException(status_code=400, detail=f"Invalid model. Choose from {list(CHAT_SERVICES.keys())}")

    chat_service = CHAT_SERVICES[model]
    return chat_service.ask_question(query)

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