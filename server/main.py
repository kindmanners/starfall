import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from psycopg2 import IntegrityError

try:
    from .database import (
        create_user, get_conversation, get_message_file, get_user_by_email,
        get_user_by_id, get_user_by_username, initialize_schema,
        list_other_users, save_message,
    )
    from .manager import manager
    from .security import ACCESS_TOKEN_EXPIRE_MINUTES, create_token, decode_token, hash_password, verify_password
except ImportError:
    from database import (
        create_user, get_conversation, get_message_file, get_user_by_email,
        get_user_by_id, get_user_by_username, initialize_schema,
        list_other_users, save_message,
    )
    from manager import manager
    from security import ACCESS_TOKEN_EXPIRE_MINUTES, create_token, decode_token, hash_password, verify_password


logger = logging.getLogger("starfall")
ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", ROOT / "uploads")).resolve()
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_schema()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Starfall database and upload storage ready")
    yield


app = FastAPI(title="Starfall", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=FRONTEND), name="assets")


class UserSignup(BaseModel):
    username: str = Field(..., min_length=3, max_length=25, pattern=r"^[A-Za-z0-9_. -]+$")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


def current_user(token: str | None):
    payload = decode_token(token) if token else None
    user_id = payload.get("user_id") if payload else None
    user = get_user_by_id(user_id) if isinstance(user_id, int) else None
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in")
    return user


def set_session_cookie(response: Response, user_id: int) -> None:
    max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    response.set_cookie(
        "access_token", create_token({"user_id": user_id}), max_age=max_age,
        httponly=True, secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="lax", path="/",
    )


def public_user(row) -> dict:
    result = dict(row)
    if result.get("created_at"):
        result["created_at"] = result["created_at"].isoformat()
    if result.get("last_message_at"):
        result["last_message_at"] = result["last_message_at"].isoformat()
    return result


def public_message(row) -> dict:
    result = dict(row)
    if result.get("created_at"):
        result["created_at"] = result["created_at"].isoformat()
    result["type"] = "dm"
    result["has_file"] = bool(result.get("file_name"))
    if result["has_file"]:
        result["file_url"] = f"/api/files/{result['id']}"
    return result


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/signup", status_code=201)
async def signup(data: UserSignup, response: Response) -> dict:
    if get_user_by_email(data.email) or get_user_by_username(data.username):
        raise HTTPException(status_code=409, detail="Email or username is already in use")
    try:
        user_id = create_user(data.username, data.email, hash_password(data.password))
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Email or username is already in use") from None
    set_session_cookie(response, user_id)
    return {"user": public_user(get_user_by_id(user_id))}


@app.post("/api/login")
async def login(data: UserLogin, response: Response) -> dict:
    user = get_user_by_email(data.email)
    if not user or not verify_password(data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    set_session_cookie(response, int(user["id"]))
    return {"user": public_user(get_user_by_id(user["id"]))}


@app.post("/api/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie("access_token", path="/")


@app.get("/api/me")
async def me(request: Request) -> dict:
    return {"user": public_user(current_user(request.cookies.get("access_token")))}


@app.get("/api/users")
async def users(request: Request) -> dict:
    user = current_user(request.cookies.get("access_token"))
    return {"users": [public_user(row) for row in list_other_users(user["id"])]}


@app.get("/api/conversations/{other_id}")
async def conversation(other_id: int, request: Request) -> dict:
    user = current_user(request.cookies.get("access_token"))
    other = get_user_by_id(other_id)
    if not other or other_id == user["id"]:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user": public_user(other),
        "messages": [public_message(row) for row in get_conversation(user["id"], other_id)],
    }


@app.post("/api/conversations/{other_id}/files", status_code=201)
async def upload_file(other_id: int, request: Request, upload: UploadFile = File(...)) -> dict:
    user = current_user(request.cookies.get("access_token"))
    if other_id == user["id"] or not get_user_by_id(other_id):
        raise HTTPException(status_code=404, detail="User not found")
    safe_name = Path(upload.filename or "attachment").name[:255]
    file_key = uuid4().hex
    destination = UPLOAD_DIR / file_key
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File is larger than 25 MB")
                output.write(chunk)
        row = save_message(
            user["id"], other_id, file_name=safe_name, file_key=file_key,
            file_size=size, file_mime=upload.content_type or "application/octet-stream",
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    message = public_message({**dict(row), "sender_name": user["username"]})
    await manager.send_to_users(message, user["id"], other_id)
    return {"message": message}


@app.get("/api/files/{message_id}")
async def download_file(message_id: int, request: Request):
    user = current_user(request.cookies.get("access_token"))
    record = get_message_file(message_id, user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="File not found")
    path = UPLOAD_DIR / record["file_key"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File is missing from storage")
    return FileResponse(path, filename=record["file_name"], media_type=record["file_mime"])


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    token = websocket.cookies.get("access_token")
    payload = decode_token(token) if token else None
    user_id = payload.get("user_id") if payload else None
    user = get_user_by_id(user_id) if isinstance(user_id, int) else None
    if not user:
        await websocket.close(code=4008)
        return
    user_id = int(user["id"])
    await manager.connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            content = str(data.get("content", "")).strip()
            recipient_id = data.get("recipient_id")
            if not isinstance(recipient_id, int) or recipient_id == user_id or not get_user_by_id(recipient_id):
                await websocket.send_json({"type": "error", "detail": "Invalid recipient"})
                continue
            if not content or len(content) > 4000:
                await websocket.send_json({"type": "error", "detail": "Message must be 1-4000 characters"})
                continue
            row = save_message(user_id, recipient_id, content)
            message = public_message({**dict(row), "sender_name": user["username"]})
            await manager.send_to_users(message, user_id, recipient_id)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket failed for user %s", user_id)
    finally:
        manager.disconnect(user_id, websocket)


@app.get("/")
async def landing_page():
    return FileResponse(FRONTEND / "index.html")


@app.get("/login")
async def login_page():
    return FileResponse(FRONTEND / "login" / "index.html")


@app.get("/chat")
async def chat_page():
    return FileResponse(FRONTEND / "chat" / "index.html")
