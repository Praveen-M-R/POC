import os
from google import genai
from google.genai import types
from core.config import GEMINI_API_KEY,MISTRAL_API_KEY,OPENAI_API_KEY
from core.prompts import MCQ_PROMPT,MCQ_EXTRACT_TOPIC
import json
from openai import OpenAI
from mistralai import Mistral
import re

class MCQGeneratorGemini:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    def upload_and_parse_file(self, file_path):
        """Uploads a file and extracts structured key topics."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"❌ File not found: {file_path}")

        try:
            ext = os.path.splitext(file_path)[-1].lower()
            if ext == ".pdf":
                with open(file_path, "rb") as file:
                    pdf_part = types.Part.from_bytes(data=file.read(), mime_type="application/pdf")
            else:
                pdf_part = self.client.files.upload(file=file_path)
            response = self.client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[pdf_part, MCQ_EXTRACT_TOPIC]
            )
            raw_topics = [topic.strip() for topic in response.text.split("\n") if topic.strip()]
            structured_topics = {}
            current_chapter = None

            for item in raw_topics:
                if re.match(r"^\d+\.\s*Chapter", item):
                    chapter_title = item.split(":", 1)[1].strip()
                    current_chapter = chapter_title
                    structured_topics[current_chapter] = []
                elif current_chapter:
                    subtopic = item.lstrip("- ").strip()
                    structured_topics[current_chapter].append(subtopic)

            return structured_topics

        except Exception as e:
            print(f"❌ Error processing file: {e}")
            return {}

    def generate_mcqs(self, selected_topics, file_paths):
        """Generates MCQs for the selected topics using uploaded files."""

        if not selected_topics:
            raise ValueError("❌ No topics selected for MCQ generation.")

        prompt = (
            f"{MCQ_PROMPT}"
            f"Generate multiple-choice questions for the following topics:\n"
            f"{', '.join(selected_topics)}\n"
        )

        try:
            pdf_parts = []
            for file_path in file_paths:
                with open(file_path, "rb") as file:
                    pdf_parts.append(types.Part.from_bytes(data=file.read(), mime_type="application/pdf"))

            response = self.client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[pdf_parts,prompt]
            )
            return response.text
        except Exception as e:
            print(f"❌ Error generating MCQs: {e}")
            return ""

class MCQGeneratorChatGPT:
    def __init__(self):
        self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
        self.thread_id = None
        self.assistant_id = None
        self.uploaded_files = {}

    def initialize_assistant_and_thread(self):
        """Initialize assistant and thread if not already created."""
        if self.assistant_id is None:
            assistant = self.openai_client.beta.assistants.create(
                instructions=MCQ_EXTRACT_TOPIC,
                model="gpt-4o-mini",
                tools=[{"type": "file_search"}],
            )
            self.assistant_id = assistant.id
        
        if self.thread_id is None:
            thread = self.openai_client.beta.threads.create()
            self.thread_id = thread.id

    def upload_file(self, file_path):
        """Uploads a file and returns its file ID, avoiding duplicate uploads."""
        if file_path in self.uploaded_files:
            return self.uploaded_files[file_path]

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"❌ File not found: {file_path}")

        try:
            with open(file_path, "rb") as file:
                uploaded_file = self.openai_client.files.create(file=file, purpose="assistants")
                file_id = uploaded_file.id
                self.uploaded_files[file_path] = file_id
                return file_id
        except Exception as e:
            print(f"❌ Error uploading file: {e}")
            return None

    def upload_and_parse_file(self, file_path):
        """Uploads a file and extracts key topics."""
        self.initialize_assistant_and_thread()
        file_id = self.upload_file(file_path)
        if not file_id:
            return []

        try:
            self.openai_client.beta.threads.messages.create(
                thread_id=self.thread_id,
                role="user",
                content=MCQ_EXTRACT_TOPIC,
                attachments=[{"file_id": file_id, "tools": [{"type": "file_search"}]}],
            )

            run = self.openai_client.beta.threads.runs.create(thread_id=self.thread_id, assistant_id=self.assistant_id)

            while True:
                status = self.openai_client.beta.threads.runs.retrieve(thread_id=self.thread_id, run_id=run.id)
                if status.status in ["completed", "failed"]:
                    break

            messages = self.openai_client.beta.threads.messages.list(thread_id=self.thread_id)
            response_text = next((msg.content[0].text.value for msg in messages.data if msg.role == "assistant"), "")
            print(response_text)
            raw_topics = [topic.strip() for topic in response_text.split("\n") if topic.strip()]
            structured_topics = {}
            current_chapter = None
            for item in raw_topics:
                if re.match(r"^\d+\.\s*Chapter", item):
                    chapter_title = item.split(":", 1)[1].strip()
                    current_chapter = chapter_title
                    structured_topics[current_chapter] = []
                elif current_chapter:
                    subtopic = item.lstrip("- ").strip()
                    structured_topics[current_chapter].append(subtopic)

            return structured_topics

        except Exception as e:
            print(f"❌ Error extracting topics: {e}")
            return []

    def generate_mcqs(self, selected_topics, file_paths):
        """Generates MCQs based on selected topics and uploaded files."""
        self.initialize_assistant_and_thread()

        if not selected_topics:
            raise ValueError("❌ No topics selected for MCQ generation.")
        if not file_paths:
            raise ValueError("❌ No files provided for reference.")

        try:
            attachments = [{"file_id": self.upload_file(path), "tools": [{"type": "file_search"}]} for path in file_paths]

            prompt = (
                f"{MCQ_PROMPT}\n"
                f"Generate multiple-choice questions for the following topics:\n"
                f"{', '.join(selected_topics)}\n"
            )

            self.openai_client.beta.threads.messages.create(
                thread_id=self.thread_id,
                role="user",
                content=prompt,
                attachments=attachments,
            )

            run = self.openai_client.beta.threads.runs.create(thread_id=self.thread_id, assistant_id=self.assistant_id)

            while True:
                status = self.openai_client.beta.threads.runs.retrieve(thread_id=self.thread_id, run_id=run.id)
                if status.status in ["completed", "failed"]:
                    break

            messages = self.openai_client.beta.threads.messages.list(thread_id=self.thread_id)
            mcqs_json = next((msg.content[0].text.value for msg in messages.data if msg.role == "assistant"), "")
            print(mcqs_json.strip())
            return mcqs_json.strip()

        except Exception as e:
            print(f"❌ Error generating MCQs: {e}")
            return "❌ Error during MCQ generation."


class MCQGeneratorMistral:
    def __init__(self):
        self.mistral_client = Mistral(api_key=MISTRAL_API_KEY)

    def upload_and_parse_file(self, file_path):
        """Uploads a file and extracts key topics."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"❌ File not found: {file_path}")

        try:
            with open(file_path, "rb") as file:
                uploaded_pdf = self.mistral_client.files.upload(
                    file={"file_name": os.path.basename(file_path), "content": file}, purpose="ocr"
                )
                signed_url = self.mistral_client.files.get_signed_url(file_id=uploaded_pdf.id).url

            messages = [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": MCQ_EXTRACT_TOPIC}]
                    + [{"type": "document_url", "document_url": signed_url}],
                }
            ]

            chat_response = self.mistral_client.chat.complete(model="mistral-small-latest", messages=messages)
            response = chat_response.choices[0].message.content
            structured_topics = {}
            current_chapter = None
            response_text=[topic.strip() for topic in response.split("\n") if topic.strip()]
            print(response_text)
            for item in response_text:
                if re.match(r"^\d+\.\s*Chapter", item):
                    chapter_title = item.split(":", 1)[1].strip()
                    current_chapter = chapter_title
                    structured_topics[current_chapter] = []
                elif current_chapter:
                    subtopic = item.lstrip("- ").strip()
                    structured_topics[current_chapter].append(subtopic)

            return structured_topics
        
        except Exception as e:
            print(f"❌ Error processing file: {e}")
            return []

    def generate_mcqs(self, selected_topics, file_paths):
        """Generates MCQs for the selected topics using uploaded files."""

        if not selected_topics:
            raise ValueError("❌ No topics selected for MCQ generation.")

        prompt = (
            f"{MCQ_PROMPT}"
            f"Generate multiple-choice questions for the following topics:\n"
            f"{', '.join(selected_topics)}\n"
        )

        try:
            pdf_parts = []
            for file_path in file_paths:
                with open(file_path, "rb") as file:
                    uploaded_pdf = self.mistral_client.files.upload(
                        file={"file_name": os.path.basename(file_path), "content": file}, purpose="ocr"
                    )
                    signed_url = self.mistral_client.files.get_signed_url(file_id=uploaded_pdf.id).url

            messages = [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}]
                    + [{"type": "document_url", "document_url": signed_url}],
                }
            ]

            chat_response = self.mistral_client.chat.complete(model="mistral-small-latest", messages=messages)
            response = chat_response.choices[0].message.content
            return response
        
        except Exception as e:
            print(f"❌ Error generating MCQs: {e}")
            return ""
