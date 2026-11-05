from fastapi import FastAPI

app = FastAPI(title="ProcureGraph AI API")


@app.get("/health/live")
def health_live():
    return {"status": "ok"}