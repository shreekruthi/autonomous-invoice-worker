import uvicorn

if __name__ == "__main__":
    uvicorn.run("worker.api:create_app", factory=True, host="127.0.0.1", port=8000, workers=1)
