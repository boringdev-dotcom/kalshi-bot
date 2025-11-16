"""FastAPI application with health check endpoint."""
from fastapi import FastAPI

app = FastAPI(title="Kalshi Bot API")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

