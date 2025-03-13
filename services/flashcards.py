import openai
import time
import json
import logging
import re
import os
from mistralai import Mistral
from core.config import OPENAI_API_KEY, MISTRAL_API_KEY, GEMINI_API_KEY
from google import genai
from google.genai import types
from core.flashcardprompt import prompt
import base64


class BaseFlashcardGenerator:
    """Base class for flashcard generators to handle common functionalities."""

    def extract_json(self, response_text):
        """Extracts JSON content from AI responses (handles Markdown formatting)."""
        json_match = re.search(r"```json\n(.*?)\n```", response_text, re.DOTALL)
        return json_match.group(1).strip() if json_match else response_text.strip()

    def parse_flashcards(self, response_text):
        """Parse AI response into structured JSON flashcards."""
        try:
            json_content = self.extract_json(response_text)
            flashcards = json.loads(json_content)
            return flashcards if isinstance(flashcards, list) else []
        except json.JSONDecodeError:
            logging.error("Invalid JSON response received")
            return []


class FlashcardGeneratorChatGPT(BaseFlashcardGenerator):
    def __init__(self):
        self.client = openai.OpenAI(api_key=OPENAI_API_KEY)
        self.mistral_client = Mistral(api_key=MISTRAL_API_KEY)

    def encode_image(self, file_path):
        """Encodes an image file to Base64."""
        with open(file_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def upload_files(self, file_paths):
        """Uploads PDFs to OpenAI and returns file IDs."""
        file_ids = []
        for file_path in file_paths:
            with open(file_path, "rb") as file:
                uploaded_file = self.client.files.create(file=file, purpose="assistants")
                file_ids.append(uploaded_file.id)

        return file_ids

    def process_txt_and_images(self, file_paths):
        """Processes TXT files using OpenAI and images using Mistral OCR."""
        extracted_texts = []
        
        for file_path in file_paths:
            ext = os.path.splitext(file_path)[1].lower()

            if ext == ".txt":
                with open(file_path, "r", encoding="utf-8") as f:
                    extracted_texts.append(f.read())

            elif ext in [".jpg", ".jpeg", ".png"]:
                base64_image = self.encode_image(file_path)
                ocr_response = self.mistral_client.ocr.process(
                    model="mistral-ocr-latest",
                    document={"type": "image_url", "image_url": f"data:image/jpeg;base64,{base64_image}"}
                )
                extracted_texts.append("\n".join(page.markdown for page in ocr_response.pages))

        return extracted_texts

    def generate_flashcards(self, file_paths):
        """Generates flashcards using ChatGPT (GPT-4o-mini)."""
        start_time = time.time()

        has_pdf = any(file.endswith(".pdf") for file in file_paths)
        has_txt_or_image = any(file.endswith((".txt", ".jpg", ".jpeg", ".png")) for file in file_paths)

        extracted_texts = self.process_txt_and_images(file_paths)

        if has_pdf:
            file_ids = self.upload_files(file_paths)

            assistant = self.client.beta.assistants.create(
                name="Flashcard Generator",
                instructions=prompt,
                model="gpt-4o-mini",
                tools=[{"type": "file_search"}],
            )

            thread = self.client.beta.threads.create()
            self.client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=prompt,
                attachments=[{"file_id": fid, "tools": [{"type": "file_search"}]} for fid in file_ids] +
                            [{"type": "text", "text": text} for text in extracted_texts]
            )

            run = self.client.beta.threads.runs.create(thread_id=thread.id, assistant_id=assistant.id)

            while True:
                time.sleep(1)
                status = self.client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
                if status.status in ["completed", "failed"]:
                    break

            messages = self.client.beta.threads.messages.list(thread_id=thread.id)
            response_text = next((msg.content[0].text.value for msg in messages.data if msg.role == "assistant"), "")

        else:
            messages = [{"role": "system", "content": prompt}]
            for text in extracted_texts:
                messages.append({"role": "user", "content": text})

            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=1000,
                temperature=0.7
            )
            response_text = response.choices[0].message.content

        flashcards = self.parse_flashcards(response_text)
        print(f"Generated {len(flashcards)} flashcards in {time.time() - start_time:.2f} seconds.")
        return flashcards


class FlashcardGeneratorMistral(BaseFlashcardGenerator):
    def __init__(self):
        self.client = Mistral(api_key=MISTRAL_API_KEY)

    def encode_image(self, file_path):
        """Encodes an image file to Base64."""
        with open(file_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def upload_files(self, file_paths):
        """Uploads PDFs to Mistral and returns signed URLs."""
        file_urls = []
        for file_path in file_paths:
            ext = os.path.splitext(file_path)[1].lower()

            if ext == ".pdf":
                with open(file_path, "rb") as file:
                    uploaded_pdf = self.client.files.upload(
                        file={"file_name": os.path.basename(file_path), "content": file}, 
                        purpose="ocr"
                    )
                    signed_url = self.client.files.get_signed_url(file_id=uploaded_pdf.id).url
                    file_urls.append(signed_url)
        
        return file_urls

    def process_txt_and_images(self, file_paths):
        """Processes TXT and Image files, returning extracted text."""
        extracted_texts = []
        
        for file_path in file_paths:
            ext = os.path.splitext(file_path)[1].lower()

            if ext == ".txt":
                with open(file_path, "r", encoding="utf-8") as f:
                    extracted_texts.append(f.read())

            elif ext in [".jpg", ".jpeg", ".png"]:
                base64_image = self.encode_image(file_path)
                ocr_response = self.client.ocr.process(
                    model="mistral-ocr-latest",
                    document={"type": "image_url", "image_url": f"data:image/jpeg;base64,{base64_image}"}
                )
                extracted_texts.append("\n".join(page.markdown for page in ocr_response.pages))

        return extracted_texts

    def generate_flashcards(self, file_paths):
        """Generates flashcards using Mistral, handling PDFs, TXT, and Images."""
        start_time = time.time()

        file_urls = self.upload_files(file_paths)

        extracted_texts = self.process_txt_and_images(file_paths)

        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
                + [{"type": "document_url", "document_url": url} for url in file_urls]
                + [{"type": "text", "text": text} for text in extracted_texts]
            }
        ]

        chat_response = self.client.chat.complete(model="mistral-small-latest", messages=messages)
        response_text = chat_response.choices[0].message.content
        
        flashcards = self.parse_flashcards(response_text)
        print(f"Generated {len(flashcards)} flashcards in {time.time() - start_time:.2f} seconds.")
        return flashcards


class FlashcardGeneratorGemini(BaseFlashcardGenerator):
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    def upload_files(self, file_paths):
        """Uploads PDFs to Gemini File API after verifying their existence."""
        uploaded_files = []

        for full_path in file_paths:
            if not os.path.exists(full_path):
                print(f"⚠️ File not found: {full_path}")
                continue
            ext = os.path.splitext(full_path)[-1].lower()
            if ext == ".pdf":
                try:
                    with open(full_path, "rb") as file:
                        pdf_part = types.Part.from_bytes(data=file.read(), mime_type="application/pdf")
                        uploaded_files.append(pdf_part)
                        print(f"✅ Uploaded: {full_path}")
                except Exception as e:
                    print(f"❌ Error uploading {full_path}: {e}")
            else:
                try:
                    myfile = self.client.files.upload(file=full_path)
                    uploaded_files.append(myfile)
                    print(f"✅ Uploaded: {full_path}")
                except Exception as e:
                    print(f"❌ Error uploading {full_path}: {e}")

        if not uploaded_files:
            raise FileNotFoundError("❌ No valid files were uploaded. Check file paths.")

        return uploaded_files

    def generate_flashcards(self, file_paths):
        """Generates flashcards using Gemini AI."""
        start_time = time.time()
        documents = self.upload_files(file_paths)

        response = self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[*documents, prompt],
        )

        response_text = getattr(response, "text", str(response))
        flashcards = self.parse_flashcards(response_text)
        print(f"Generated {len(flashcards)} flashcards in {time.time() - start_time:.2f} seconds.")
        return flashcards
