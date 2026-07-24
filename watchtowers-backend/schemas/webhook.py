from pydantic import BaseModel
from typing import Dict, Any
import uuid

class Event(BaseModel):
    topic_id: uuid.UUID
    payload: Dict[str, Any]
