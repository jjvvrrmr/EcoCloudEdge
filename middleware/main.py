import os
import httpx
from fastapi import FastAPI, Request, HTTPException
import uvicorn

app = FastAPI()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama.ollama.svc.cluster.local:11434/api/generate")
MODEL = os.getenv("MODEL", "tinyllama")

@app.post("/webhook")
async def handle_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    
    prompt = data.get("text", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing text parameter")

    payload = {
        "model": MODEL,
        "prompt": f"Resume el siguiente texto legal: {prompt}",
        "stream": False
    }

    # Tiempo de espera elevado para inferencia en CPU (5 minutos)
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            response = await client.post(OLLAMA_URL, json=payload)
            response.raise_for_status()
            # Se fuerza el decodificado UTF-8 para evitar errores con tildes y eñes
            result = response.json()
            return {"summary": result.get("response", "")}
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Ollama connection error: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)