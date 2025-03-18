from passlib.context import CryptContext
from datetime import datetime, timedelta
import jwt
from datastorage.db_connect import users_collection
from bson import ObjectId
from fastapi import HTTPException

SECRET_KEY = "demo"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.now() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str):
    try:
        return {"payload": jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]), "new_token": None}

    except jwt.ExpiredSignatureError:
        expired_payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
        user_id = expired_payload.get("sub")

        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        new_token = create_access_token(data={"sub": str(user["_id"])})
        return {"payload": expired_payload, "new_token": new_token}

    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_user_by_username(username: str):
    return users_collection.find_one({"username": username})

def get_user_by_id(user_id: str):
    return users_collection.find_one({"_id": ObjectId(user_id)})
