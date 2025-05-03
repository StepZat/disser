import logging

from dns.edns import Option
from fastapi import FastAPI, HTTPException, Query
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict
from bson import ObjectId
import motor.motor_asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.error")

# MongoDB connection
title = "MongoDB connection"
client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://192.168.2.52:27017/replicaSet=rs1")
db = client['logstash_db']
collection = db['dhcp_logs']

# FastAPI app
app = FastAPI(debug=True)

@app.on_event("startup")
async def startup_db_client():
    try:
        await client.admin.command("ping")
        logger.debug("Connected to MongoDB!")
    except Exception as e:
        logger.error("Could not connect to MongoDB: %s", e)

# Helper to convert ObjectId to string
def as_str_id(doc: dict) -> dict:
    doc['_id'] = str(doc['_id'])
    return doc

# Pydantic model for logs
class LogModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )
    id: str = Field(alias="_id")
    Timestamp: Optional[str] = None
    Log_Level: Optional[str] = None
    Hostname: Optional[str] = None
    Info_message: Optional[str] = None
    predicted_message_type: Optional[str] = None

@app.get("/logs", response_model=List[LogModel], tags=["logs"])
async def list_logs(
    count: int = Query(10, ge=1),
    log_type: Literal["all", "safe", "dangerous"] = Query("all", alias="type")
):
    """
    Get list of logs with optional filters:
    - count: maximum number of logs to return
    - type: 'all' | 'safe' | 'dangerous'
    """
    try:
        # Build filter based on query param
        if log_type == "safe":
            query_filter = {"predicted_message_type": "Safe"}
        elif log_type == "dangerous":
            query_filter = {"predicted_message_type": {"$ne": "Safe"}}
        else:
            query_filter = {}

        # Fetch and limit results
        logs = []
        cursor = (
            collection.find(query_filter)
            .sort("@timestamp", -1)
            .limit(count)
        )
        async for doc in cursor:
            logs.append(LogModel(**as_str_id(doc)))
        return logs
    except Exception as e:
        logger.exception("Error fetching logs")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

# To run:
# uvicorn main:app --reload --host 0.0.0.0 --port 8000 --log-level debug

# uvicorn main:app --reload --host 0.0.0.0 --port 8000 --log-level debug