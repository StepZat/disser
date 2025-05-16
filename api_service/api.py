# main.py
import logging
import os
import sqlite3
from datetime import datetime
from typing import List, Optional, Literal

import psutil
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from bson import ObjectId
import motor.motor_asyncio
from fastapi.middleware.cors import CORSMiddleware

# создаём приложение и настраиваем CORS
app = FastAPI(debug=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # на проде лучше сузить
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# коннект к Mongo
client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://192.168.2.52:27017/")
db     = client["events"]
col    = db["logs"]

# логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.error")

# приводим ObjectId к строке
def as_str_id(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    # если у вас в БД поле "@timestamp" — оно остаётся нетронутым здесь
    return doc

# Pydantic-модели
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
    # теперь по умолчанию до 10 000 записей
    count:     int                     = Query(10_000, ge=1),
    skip:      int                     = Query(0, ge=0),
    type:      Literal["all","safe","dangerous"] = Query("all"),
    log_level: Optional[str]           = Query(None),
    hostname:  Optional[str]           = Query(None),
    search:    Optional[str]           = Query(None, description="подстрока в Info_message"),
    start:     Optional[datetime]      = Query(None, description="начало диапазона @timestamp (ISO)"),
    end:       Optional[datetime]      = Query(None, description="конец диапазона @timestamp (ISO)")
):
    """
    Пагинация + фильтрация по:
      - type: all|safe|dangerous
      - log_level (включая NOTIFY)
      - hostname (regex)
      - search в Info_message
      - диапазону @timestamp
    """
    try:
        q: dict = {}

        # 1) safe/dangerous
        if type == "safe":
            q["predicted_message_type"] = "Safe"
        elif type == "dangerous":
            q["predicted_message_type"] = {"$ne": "Safe"}

        # 2) уровень лога
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
            tf = {}
            if start: tf["$gte"] = start.isoformat()
            if end:   tf["$lte"] = end.isoformat()
            q["Timestamp"] = tf

        # общее число совпадений
        total  = await col.count_documents(q)

        # возвращаем данные (упорядочено по @timestamp)
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
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.get("/health", tags=["health"])
async def health():
    """
    Возвращает список сервисов со статусами из SQLite (таблица Service).
    Читает напрямую через sqlite3, без ORM.
    """
    db_path = os.environ.get("SQLITE_DB_PATH", "./db.sqlite3")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name, last_is_up FROM dashboard_app_service")
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        logger.exception("Error reading Service table")
        raise HTTPException(status_code=500, detail="Cannot fetch service health")

    services = []
    for name, raw_status in rows:
        s = str(raw_status).strip().lower()
    # все, что не 'up'/true/1/healthy — считаем down
        status_norm = "up" if s in ("up", "true", "1", "healthy") else "down"
        services.append({"name": name, "status": status_norm})
    return {"services": services}

@app.get("/hosts/health", tags=["hosts"])
async def hosts_health():
    """
    Возвращает список всех хостов и их статусы из таблицы dashboard_app_hosts.
    Поле is_up (1/0, True/False) приводится к 'up'/'down'.
    """
    db_path    = os.environ.get("SQLITE_DB_PATH", "./db.sqlite3")
    table_name = os.environ.get("HOSTS_TABLE", "dashboard_app_host")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Предполагаем, что в таблице есть столбцы 'hostname' и 'is_up'
        cursor.execute(f"SELECT name, address, is_up FROM {table_name}")
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        logger.exception("Error reading hosts status table")
        raise HTTPException(status_code=500, detail=f"Cannot fetch hosts health: {e}")

    hosts = []
    for hostname, address, is_up in rows:
        s = str(is_up).strip().lower()
        status = "up" if s in ("1", "true", "yes") else "down"
        hosts.append({"name": hostname, "address": address, "status": status})
    return {"hosts": hosts}

@app.get("/metrics/system")
async def system_metrics():
    cpu, ram, storage = psutil.cpu_percent(), psutil.virtual_memory().percent, psutil.disk_usage("/").percent
    la1, la5, la15 = psutil.getloadavg()
    return {"cpu": cpu, "ram": ram, "storage": storage,
            "la1": la1, "la5": la5, "la15": la15}