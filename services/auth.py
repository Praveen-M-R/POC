from passlib.context import CryptContext
from datetime import datetime, timedelta
import jwt
from datastorage.db_connect import users_collection
from fastapi import HTTPException
from google.cloud.firestore_v1 import FieldFilter

SECRET_KEY = "demo"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hashes a password using bcrypt."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies if the provided password matches the stored hash."""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    """Creates a JWT access token with expiration."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str):
    """Decodes a JWT token and refreshes it if expired."""
    try:
        return {"payload": jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]), "new_token": None}

    except jwt.ExpiredSignatureError:
        expired_payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
        user_id = expired_payload.get("sub")

        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        new_token = create_access_token(data={"sub": user["id"]})
        return {"payload": expired_payload, "new_token": new_token}

    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_user_by_username(username: str):
    """Fetches a user by username from Firestore."""
    query = users_collection.where(filter=FieldFilter("username", "==", username)).limit(1).stream()
    users = [doc.to_dict() | {"id": doc.id} for doc in query]
    return users[0] if users else None

async def get_user_by_id(user_id: str):
    """Fetches a user by ID from Firestore."""
    user_ref = users_collection.document(user_id).get()
    return user_ref.to_dict() | {"id": user_id} if user_ref.exists else None
