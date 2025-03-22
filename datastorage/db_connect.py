from pymongo import MongoClient
from core.config import MONGODB_URI

client = MongoClient(MONGODB_URI)
db = client['notesight']

users_collection = db['users']
reports_collection = db['reports']

def save_student_report(report):
    """Saves the generated student report to MongoDB."""
    result = reports_collection.insert_one(report)
    report['_id'] = str(result.inserted_id)
    return report

def close_connection():
    client.close()