# main.py
import logging
from datetime import datetime
from typing import List, Optional, Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from bson import ObjectId
import motor.motor_asyncio
from fastapi.middleware.cors import CORSMiddleware

# --- Настраиваем CORS сразу после создания app ---
app = FastAPI(debug=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # или ["http://localhost:8000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB
client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://192.168.2.53:27017/")
db     = client["events"]
col    = db["logs"]

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.error")

# Преобразуем ObjectId и @timestamp → Timestamp
def as_str_id(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    # Забираем из Mongo поле "@timestamp" и кладём его в "Timestamp" для Pydantic
    if "@timestamp" in doc:
        doc["Timestamp"] = doc.pop("@timestamp")
    return doc

# Pydantic-модель
class LogModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)
    id: str                   = Field(alias="_id")
    Timestamp: Optional[datetime]
    Log_Level: Optional[str]
    Hostname: Optional[str]
    Info_message: Optional[str]
    predicted_message_type: Optional[str]

class LogsResponse(BaseModel):
    total: int
    data: List[LogModel]

@app.on_event("startup")
async def startup_db_client():
    try:
        await client.admin.command("ping")
        logger.info("Connected to MongoDB!")
    except Exception as e:
        logger.error("Could not connect to MongoDB: %s", e)

@app.get("/logs", response_model=LogsResponse, tags=["logs"])
async def list_logs(
    count:     int                     = Query(10, ge=1),
    skip:      int                     = Query(0, ge=0),
    type:      Literal["all","safe","dangerous"] = Query("all"),
    log_level: Optional[str]           = Query(None),
    hostname:  Optional[str]           = Query(None),
    search:    Optional[str]           = Query(None, description="подстрока в Info_message"),
    start:     Optional[datetime]      = Query(None, description="начало диапазона (ISO)"),
    end:       Optional[datetime]      = Query(None, description="конец диапазона (ISO)")
):
    """
    Пагинация + фильтрация по:
      - типу сообщения (safe/dangerous)
      - лог-уровню (включая NOTIFY)
      - hostname (regex, case-insensitive)
      - подстроке в Info_message
      - диапазону @timestamp
    """
    try:
        q: dict = {}

        # 1) фильтр по безопасному/опасному
        if type == "safe":
            q["predicted_message_type"] = "Safe"
        elif type == "dangerous":
            q["predicted_message_type"] = {"$ne": "Safe"}

        # 2) лог-уровень (DEBUG, INFO, …, NOTIFY)
        if log_level:
            q["Log_Level"] = log_level

        # 3) hostname через regex
        if hostname:
            q["Hostname"] = {"$regex": hostname, "$options": "i"}

        # 4) поиск по сообщению
        if search:
            q["Info_message"] = {"$regex": search, "$options": "i"}

        # 5) диапазон по @timestamp
        if start or end:
            tf: dict = {}
            if start: tf["$gte"] = start
            if end:   tf["$lte"] = end
            q["@timestamp"] = tf

        total  = await col.count_documents(q)
        cursor = (
            col.find(q)
               .sort("@timestamp", -1)
               .skip(skip)
               .limit(count)
        )
        docs = [LogModel(**as_str_id(d)) async for d in cursor]

        return {"total": total, "data": docs}

    except Exception as e:
        logger.exception("Error fetching logs")
        raise HTTPException(500, f"Internal server error: {e}")
