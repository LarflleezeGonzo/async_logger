from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from elasticsearch import Elasticsearch, AsyncElasticsearch
from elasticsearch.helpers import bulk
from typing import List
import asyncio

app = FastAPI()

origins = [
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


es = Elasticsearch("http://elasticsearch:9200")


class MetadataItem(BaseModel):
    parentResourceId: str

    class Config:
        json_schema_extra = {
            "examples": [{"parentResourceId": "example-parent-resource-id"}]
        }


class LogItem(BaseModel):
    level: str
    message: str
    resourceId: str
    timestamp: str
    traceId: str
    spanId: str
    commit: str
    metadata: MetadataItem

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "level": "error",
                    "message": "Failed to connect to DB",
                    "resourceId": "server-1234",
                    "timestamp": "2023-09-15T08:00:00Z",
                    "traceId": "abc-xyz-123",
                    "spanId": "span-456",
                    "commit": "5e5342f",
                    "metadata": {"parentResourceId": "example-parent-resource-id"},
                }
            ]
        }


async def index_logs(log_items: List[LogItem]):
    actions = [
        {
            "_op_type": "index",
            "_index": "logs",
            "_source": log_item.model_dump(),
        }
        for log_item in log_items
    ]

    try:
        bulk(es, actions, headers={"Content-Type": "application/json"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error indexing logs: {e}")


@app.post("/ingest")
async def ingest_log(log_items: List[LogItem], background_tasks: BackgroundTasks):
    background_tasks.add_task(index_logs, log_items)
    return {"status": es.info()}


@app.get("/query")
async def query_logs(
    level: str = Query(None, title="Log Level"),
    message: str = Query(None, title="Log Message"),
    resourceId: str = Query(None, title="Resource ID"),
    timestamp: str = Query(None, title="Timestamp"),
    traceId: str = Query(None, title="Trace ID"),
    spanId: str = Query(None, title="Span ID"),
    commit: str = Query(None, title="Commit"),
    parentResourceId: str = Query(None, title="Parent Resource ID"),
    timestamp_from: str = Query(None, title="Timestamp From"),
    timestamp_to: str = Query(None, title="Timestamp To"),
):
    es_query = {"query": {"bool": {"must": []}}}

    filters = [
        {"term": {"level": level}} if level else None,
        {"match": {"message": message}} if message else None,
        {"term": {"resourceId": resourceId}} if resourceId else None,
        {"term": {"timestamp": timestamp}} if timestamp else None,
        {"term": {"traceId": traceId}} if traceId else None,
        {"term": {"spanId": spanId}} if spanId else None,
        {"term": {"commit": commit}} if commit else None,
        {"term": {"metadata.parentResourceId": parentResourceId}}
        if parentResourceId
        else None,
    ]

    es_query["query"]["bool"]["must"] = [f for f in filters if f is not None]

    if timestamp_from:
        es_query["query"]["bool"]["must"].append(
            {"range": {"timestamp": {"gte": timestamp_from}}}
        )

    if timestamp_to:
        es_query["query"]["bool"]["must"].append(
            {"range": {"timestamp": {"lte": timestamp_to}}}
        )

    try:
        result = es.search(index="logs", body=es_query)
        logs = result["hits"]["hits"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing query: {e}")

    return {"logs": logs}


async def get_elasticsearch():
    return es
