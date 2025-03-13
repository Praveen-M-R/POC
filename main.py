from fastapi import FastAPI, status
from api.endpoints import router
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

@app.get("/home", status_code=status.HTTP_200_OK)
def home():
    return {"message": "Welcome to Notesight Intelligence Systems!"}

@app.get("/health", status_code=status.HTTP_200_OK)
def health():
    return {"status": "Up and Healthy!"}