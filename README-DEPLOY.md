# SyncroVibe TTS API — Railway/Render 배포 가이드

## 0. 먼저 알아야 할 것 (중요)

이 API는 torch + MeloTTS + OpenVoice + transformers 등 **무거운 스택**입니다.
실측 기준(맥에서 개발할 때 겪은 문제들 참고) 모델 로딩만으로 RAM을 1GB 이상
쓸 가능성이 높습니다.

- **Render 무료 티어**: RAM 512MB → 모델 로딩 중 죽을 가능성이 큽니다.
- **Railway**: 무료 체험 크레딧(~$5)으로 시작하지만, 크레딧 소진 후 유료.
  다만 리소스 제한이 Render 무료보다 넉넉해서 "일단 되게 만들기"는 여기가 낫습니다.

결론: **Railway로 시도하는 걸 추천**하고, 그래도 메모리 부족(OOM)으로 죽으면
Railway의 유료 플랜(월 $5~ 부터, RAM 늘릴 수 있음)으로 전환해야 할 수 있습니다.
이 부분은 팀에 미리 공유해두는 게 좋습니다 — "무료로 안 될 수도 있다"는 리스크.

## 1. checkpoints_v2 폴더 채우기 (필수, 빠져있음)

전달받은 zip에는 `checkpoints_v2/converter/`가 빠져 있습니다. 로컬 macOS에서
작업할 때 이미 받아둔 그 폴더를 그대로 여기 복사하세요:

```
deploy_pkg/
├── api.py
├── tts_generator.py
├── requirements.txt
├── Dockerfile
├── voices/
│   ├── ref_male.wav
│   └── ref_female.wav
└── checkpoints_v2/
    └── converter/
        ├── config.json
        └── checkpoint.pth      <- 이게 있어야 함
```

없다면 OpenVoice 공식 저장소(https://github.com/myshell-ai/OpenVoice) 안내를
따라 V2 체크포인트를 다시 받아야 합니다.

## 2. 로컬에서 Docker로 먼저 테스트 (강력 추천)

Railway에 바로 올리기 전에 로컬에서 이미지가 빌드/실행되는지 확인하세요.
클라우드에서 실패하면 로그 보기가 훨씬 불편합니다.

```bash
cd deploy_pkg
docker build -t syncrovibe-tts .
docker run -p 8000:8000 syncrovibe-tts
```

기동 후:

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/generate \
     -H "Content-Type: application/json" \
     -d '{"text":"안녕하세요 test","gender":"female"}' \
     --output out.wav
```

`out.wav`가 정상 생성되면 배포 준비 완료.

## 3. Railway 배포

1. https://railway.app 가입 (GitHub 계정 연동 추천)
2. 이 `deploy_pkg` 폴더를 별도 GitHub 저장소로 push
   (checkpoints_v2가 커서 Git LFS가 필요할 수 있음 — 안 되면 Railway CLI로
   로컬에서 직접 배포하는 방법 사용, 아래 3-B 참고)
3. Railway 대시보드 → New Project → Deploy from GitHub repo → 저장소 선택
4. Railway가 `railway.toml`을 읽어 Dockerfile 빌드로 자동 진행
5. Settings → Networking → Generate Domain 눌러서 공개 URL 발급
6. 발급된 URL + `/health` 로 살아있는지 확인

### 3-B. GitHub 없이 CLI로 바로 배포하는 방법 (checkpoints 용량 문제 회피)

```bash
npm install -g @railway/cli
railway login
cd deploy_pkg
railway init
railway up
```

이 방법은 로컬 폴더를 그대로 업로드하므로 Git/LFS 신경 안 써도 됩니다.

## 4. Render로 배포하고 싶다면

Render는 Dashboard → New → Web Service → GitHub repo 연결 → 아래 값 입력:

- Environment: Docker
- Dockerfile Path: `./Dockerfile`
- Instance Type: 최소 Starter(유료) 권장. Free는 위에서 설명한 이유로
  실패 가능성이 높습니다.

## 5. 배포 후 흔한 문제

- **빌드는 성공했는데 계속 재시작(크래시 루프)** → 메모리 부족(OOM)일 확률
  높음. 플랜을 올리거나, torch를 CPU 전용 경량 빌드로 바꾸는 것도 고려.
- **첫 요청이 아주 느림/타임아웃** → 모델이 시작 시 1회 로딩되는데(수십초~1분),
  플랫폼의 헬스체크 타임아웃이 짧으면 죽은 걸로 오판할 수 있음.
  `railway.toml`에 `healthcheckTimeout = 300`을 이미 넣어뒀음.
- **한국어 몇 글자만 되고 나머지는 에러** → nltk 데이터(cmudict 등)가
  빌드 중 다운로드 실패했을 가능성. Dockerfile의 해당 RUN 줄 로그 확인.
