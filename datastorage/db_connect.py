import firebase_admin
from firebase_admin import credentials, firestore
from core.config import FIREBASE_CREDENTIALS_PATH 
import json
import os
# Initialize Firebase
cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Firestore collections
users_collection = db.collection("users")
reports_collection = db.collection("reports")

def save_student_report(report):
    """Saves the generated student report to Firestore."""
    doc_ref = reports_collection.add(report)
    report["_id"] = doc_ref[1].id  # Firestore auto-generates an ID
    return report

if not firebase_admin._apps:
    firebase_creds = os.getenv("FIREBASE_CREDS")
    cred_dict = json.loads(firebase_creds)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
db = firestore.client()