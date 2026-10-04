from fastapi import FastAPI


app = FastAPI(
    title="AgentHire OS API",
    description="Backend API for AgentHire OS.",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "agenthire-api",
        "version": "0.1.0",
    }
