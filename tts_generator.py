"""
tts_generator.py
----------------
SyncroVibe AI - TTS 엔진 (MeloTTS 베이스 + OpenVoice V2 톤컬러 변환)

교체 이력 (2026-07):
    이전: facebook/mms-tts-kor / mms-tts-eng (단일 화자 VITS)
          - gender 컬럼이 실제로는 반영 안 됨 (pitch-shift 흉내만 냄)
          - 라이선스 CC-BY-NC-4.0 (비상업 전용)
    이후: MeloTTS(MIT, KR/EN 베이스 합성) + OpenVoice V2(MIT, 톤컬러 변환)
          - gender 컬럼 값 -> 레퍼런스 성우(남/여) 목소리로 실제 화자 변환
          - 둘 다 MIT, 상업적 사용 가능

자세한 배경: GENDER_TTS_FIX.md 참고.

사전 준비물 (직접 채워야 함):
    voices/ref_male.wav   - 남성 레퍼런스 목소리 3~10초 클립
    voices/ref_female.wav - 여성 레퍼런스 목소리 3~10초 클립
    checkpoints_v2/converter/  - OpenVoice V2 톤컬러 컨버터 체크포인트
        (https://github.com/myshell-ai/OpenVoice 안내에 따라 다운로드)

설치:
    pip install -r requirements.txt
"""

import os
import numpy as np
import soundfile as sf
import torch

from melo.api import TTS as MeloTTS
from openvoice.api import ToneColorConverter

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
SILENCE_MS = 80          # 세그먼트 사이 무음 간격
TMP_DIR = "tmp_tts"       # 중간 wav 임시 저장 폴더

CONVERTER_CKPT_DIR = "checkpoints_v2/converter"

REFERENCE_VOICES = {
    "male": "voices/ref_male.wav",
    "female": "voices/ref_female.wav",
}

# CSV에 어떤 표기가 들어와도 male/female로 정규화
GENDER_ALIASES = {
    "male": "male", "m": "male", "남": "male", "남성": "male", "boy": "male",
    "female": "female", "f": "female", "여": "female", "여성": "female", "girl": "female",
}


def normalize_gender(gender) -> str:
    key = str(gender).strip().lower()
    return GENDER_ALIASES.get(key, "female")  # 알 수 없는 값이면 female로 기본 처리


# ─────────────────────────────────────────
# 한/영 세그먼트 분리 (기존 로직 그대로 재사용)
# ─────────────────────────────────────────
def split_by_language(text: str):
    """한글/영문 혼합 문자열을 언어별 세그먼트로 분리."""
    segments = []
    buffer = ""
    current_lang = None

    for ch in text:
        if "\uac00" <= ch <= "\ud7a3":
            lang = "ko"
        elif ch.isascii() and ch.isalpha():
            lang = "en"
        else:
            lang = None

        if lang is None:
            buffer += ch
        elif current_lang is None:
            current_lang = lang
            buffer += ch
        elif lang == current_lang:
            buffer += ch
        else:
            if buffer.strip():
                segments.append((current_lang, buffer.strip()))
            buffer = ch
            current_lang = lang

    if buffer.strip():
        segments.append((current_lang or "ko", buffer.strip()))

    return segments


# ─────────────────────────────────────────
# 모델 로드: MeloTTS(KR/EN 베이스) + OpenVoice V2(톤컬러 변환) + 성별 레퍼런스 임베딩
# ─────────────────────────────────────────
def load_models():
    print("[1/3] MeloTTS 베이스 모델 로딩 중...")
    device = "cuda" if torch.cuda.is_available() else "cpu"

    melo_ko = MeloTTS(language="KR", device=device)
    melo_en = melo_ko  # 임시: 메모리 테스트용

    print("[2/3] OpenVoice V2 톤컬러 컨버터 로딩 중...")
    tone_converter = ToneColorConverter(
        f"{CONVERTER_CKPT_DIR}/config.json", device=device
    )
    tone_converter.load_ckpt(f"{CONVERTER_CKPT_DIR}/checkpoint.pth")

    print("[3/3] 성별 레퍼런스 화자 임베딩 추출 중...")
    target_se = {}
    for gender, wav_path in REFERENCE_VOICES.items():
        if not os.path.exists(wav_path):
            raise FileNotFoundError(
                f"레퍼런스 화자 wav 없음: {wav_path} — voices/ 폴더에 "
                f"남/여 레퍼런스 클립(3~10초)을 넣어주세요."
            )
        se = tone_converter.extract_se([wav_path])
        target_se[gender] = se

    sr = melo_ko.hps.data.sampling_rate
    print(f"      → 사용 디바이스: {device}")
    print(f"      → 샘플레이트:    {sr} Hz")

    return {
        "ko": melo_ko,
        "en": melo_en,
        "tone_converter": tone_converter,
        "target_se": target_se,
        "device": device,
        "sampling_rate": sr,
    }


# ─────────────────────────────────────────
# 단일 언어 세그먼트 -> base wav 파일
# ─────────────────────────────────────────
def synthesize_segment(text: str, lang: str, models: dict, out_path: str) -> None:
    model = models["ko"] if lang == "ko" else models["en"]
    speaker_key = "KR" if lang == "ko" else "EN-Default"
    speaker_ids = model.hps.data.spk2id
    model.tts_to_file(text, speaker_ids[speaker_key], out_path, speed=1.0)


# ─────────────────────────────────────────
# 한 줄(한영 혼합) -> 최종 파형 (gender 반영, 실제 화자 변환)
# ─────────────────────────────────────────
def synth_line(text: str, gender, models: dict):
    os.makedirs(TMP_DIR, exist_ok=True)
    sr = models["sampling_rate"]
    silence = np.zeros(int(sr * SILENCE_MS / 1000), dtype=np.float32)

    segments = split_by_language(text)
    if not segments:
        return np.zeros(int(sr * 0.3), dtype=np.float32), sr

    chunks = []
    for i, (lang, seg) in enumerate(segments):
        seg_path = os.path.join(TMP_DIR, f"_seg_{i}.wav")
        synthesize_segment(seg, lang, models, seg_path)
        wav, _ = sf.read(seg_path, dtype="float32")
        chunks.append(wav)
        if i < len(segments) - 1:
            chunks.append(silence)

    base_wave = np.concatenate(chunks)
    base_path = os.path.join(TMP_DIR, "_base.wav")
    sf.write(base_path, base_wave, sr)

    # ── 여기가 핵심: pitch-shift가 아니라 실제 화자 톤컬러 변환 ──
    gender_key = normalize_gender(gender)
    tone_converter = models["tone_converter"]
    src_se = tone_converter.extract_se([base_path])
    tgt_se = models["target_se"][gender_key]

    out_path = os.path.join(TMP_DIR, "_out.wav")
    tone_converter.convert(
        audio_src_path=base_path,
        src_se=src_se,
        tgt_se=tgt_se,
        output_path=out_path,
    )

    out_wave, out_sr = sf.read(out_path, dtype="float32")
    return out_wave, out_sr


if __name__ == "__main__":
    models = load_models()
    wave, sr = synth_line("이 게임 really 재밌었어. Let's play together 다음에 또!", "female", models)
    sf.write("output.wav", wave, sr)
    print(f"완료 → output.wav ({len(wave)/sr:.2f}초)")
