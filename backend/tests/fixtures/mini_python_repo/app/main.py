"""Entry point of the mini FastAPI app used by CodeCompass tests."""

from fastapi import FastAPI

from app.api.users import router as users_router

app = FastAPI(title="Mini")
app.include_router(users_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
