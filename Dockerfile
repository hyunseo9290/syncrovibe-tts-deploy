FROM python:3.11-slim

WORKDIR /app

# 빌드 도구 (mecab-python3, wavmark 등 소스 빌드가 필요한 패키지용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# MeloTTS / OpenVoice는 PyPI 정식 패키지가 아니라 GitHub에서 직접 설치.
# --no-deps 필수: 두 저장소의 setup.py가 아주 낡은 버전을 강제로 요구해서
# 위 requirements.txt로 이미 깔아둔 최신 버전들과 충돌한다.
RUN pip install --no-cache-dir --no-deps git+https://github.com/myshell-ai/MeloTTS.git
RUN pip install --no-cache-dir --no-deps git+https://github.com/myshell-ai/OpenVoice.git

# 영어 g2p용 NLTK 데이터
RUN python -c "import nltk; nltk.download('cmudict'); nltk.download('averaged_perceptron_tagger')"

# 앱 코드 + 레퍼런스 음성 + OpenVoice 체크포인트
COPY api.py tts_generator.py ./
COPY voices ./voices
COPY checkpoints_v2 ./checkpoints_v2

# 최초 임포트 시 melo가 huggingface에서 토크나이저를 내려받는다.
# 배포 환경에 따라 속도 저하가 있을 수 있으니 미리 캐시를 굽고 싶다면
# 여기서 한 번 임포트해 볼 수도 있음 (선택사항, 실패해도 무시):
# RUN python -c "from melo.api import TTS" || true

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT}"]
