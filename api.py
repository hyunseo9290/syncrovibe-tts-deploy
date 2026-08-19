"""
api.py — SyncroVibe TTS 경량 API
--------------------------------
텍스트 + 성별을 받아 음성 wav 파일 하나를 바로 돌려주는 단일 엔드포인트.
무거운 배치 파이프라인(CSV/Rhubarb/ZIP) 없이, 딱 합성만 한다.

엔드포인트:
    POST /generate   -> wav 파일 바이너리 응답 (audio/wav)
    GET  /health     -> 서버/모델 상태 확인
    GET  /           -> 간단한 사용법 안내

실행:
    pip install fastapi "uvicorn[standard]" python-multipart
    uvicorn api:app --host 0.0.0.0 --port 8000

호출 예 (curl):
    curl -X POST http://localhost:8000/generate \
         -H "Content-Type: application/json" \
         -d '{"text":"안녕하세요 this is a test 반갑습니다","gender":"female"}' \
         --output out.wav

주의:
    - 모델(MeloTTS + OpenVoice)은 서버 시작 시 1회만 로딩한다(요청마다 로딩하면 느림).
    - CPU 환경에서는 한 요청에 수십 초 걸릴 수 있다(GPU 권장).
    - tts_generator.py, voices/, checkpoints_v2/ 가 같은 폴더에 있어야 한다.
"""

import io
import os
import tempfile

import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, field_validator

from tts_generator import load_models, synth_line, normalize_gender

# ─────────────────────────────────────────
# 요청 스키마
# ─────────────────────────────────────────
class GenerateRequest(BaseModel):
    text: str
    gender: str = "female"

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("text는 비어 있을 수 없습니다.")
        if len(v) > 500:
            raise ValueError("text는 500자 이하여야 합니다.")
        return v.strip()

    @field_validator("gender")
    @classmethod
    def gender_valid(cls, v):
        # male/female/남/여/m/f 등 다양한 표기를 tts_generator가 정규화하므로
        # 여기서는 정규화 결과가 male/female 중 하나인지만 확인
        norm = normalize_gender(v)
        if norm not in ("male", "female"):
            raise ValueError("gender는 male 또는 female 이어야 합니다.")
        return v


# ─────────────────────────────────────────
# 앱 + 모델 (시작 시 1회 로딩)
# ─────────────────────────────────────────
app = FastAPI(
    title="SyncroVibe TTS API",
    description="텍스트+성별 → 음성 wav 하나를 돌려주는 경량 TTS 엔드포인트",
    version="1.0.0",
)

MODELS = None  # 지연 로딩 (첫 요청 또는 startup에서 채움)


@app.on_event("startup")
def _load_on_startup():
    """서버가 뜰 때 모델을 미리 로딩해 둔다(첫 요청 지연 방지)."""
    global MODELS
    if MODELS is None:
        print("모델 로딩 중... (MeloTTS + OpenVoice V2, 수십 초 소요)")
        MODELS = load_models()
        print("모델 로딩 완료. /generate 요청을 받을 준비가 되었습니다.")


def _get_models():
    global MODELS
    if MODELS is None:
        MODELS = load_models()
    return MODELS


# ─────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────
@app.get("/")
def root():
    return {
        "service": "SyncroVibe TTS API",
        "usage": {
            "endpoint": "POST /generate",
            "body": {"text": "합성할 대사 (한/영 혼용 가능)", "gender": "male | female"},
            "response": "audio/wav 바이너리",
        },
        "example_curl": (
            "curl -X POST http://localhost:8000/generate "
            "-H 'Content-Type: application/json' "
            "-d '{\"text\":\"안녕하세요 test\",\"gender\":\"female\"}' "
            "--output out.wav"
        ),
    }


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": MODELS is not None}


@app.post("/generate")
def generate(req: GenerateRequest):
    """
    텍스트+성별 → wav 바이너리.
    성공 시 audio/wav 스트림을 반환한다.
    """
    models = _get_models()
    try:
        wave, sr = synth_line(req.text, req.gender, models)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"합성 실패: {e}")

    # numpy 파형 -> 메모리 상의 wav 바이트로 인코딩(디스크에 안 남김)
    buf = io.BytesIO()
    sf.write(buf, wave, sr, format="WAV")
    buf.seek(0)

    gender_norm = normalize_gender(req.gender)
    headers = {
        "Content-Disposition": f'attachment; filename="tts_{gender_norm}.wav"',
        "X-Sample-Rate": str(sr),
        "X-Gender": gender_norm,
    }
    return StreamingResponse(buf, media_type="audio/wav", headers=headers)


# 로컬에서 `python api.py` 로도 실행 가능하게
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)
