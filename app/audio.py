"""Transcrição local substituível, sem enviar áudio ao modelo de atendimento."""
import io
import os
import threading
from pathlib import Path
from .usage import record
import time

_model = None
_model_lock = threading.Lock()
_slot = threading.BoundedSemaphore(1)


def model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            cache = Path(os.getenv("LOCALAPPDATA", Path.home())) / "Lumi" / "speech-models"
            _model = WhisperModel(os.getenv("LUMI_AUDIO_MODEL", "base"), device="cpu", compute_type="int8",
                cpu_threads=4, download_root=str(cache))
        return _model


def audio_format(data):
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE": return "wav"
    if data.startswith(b"OggS"): return "ogg"
    if data.startswith(b"\x1aE\xdf\xa3"): return "matroska"
    if data[4:8] == b"ftyp": return "mov"
    if data.startswith(b"ID3") or (len(data)>1 and data[0]==255 and data[1]&224==224): return "mp3"
    raise ValueError("Envie um áudio WAV, MP3, M4A, OGG ou WebM válido.")


def decode(data):
    import av
    import numpy as np
    chunks = []; count = 0
    try:
        with av.open(io.BytesIO(data), format=audio_format(data), options={"protocol_whitelist": "file,pipe"}) as container:
            if not container.streams.audio: raise ValueError()
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            for frame in container.decode(container.streams.audio[0]):
                for converted in resampler.resample(frame):
                    count += converted.samples
                    if count > 120*16000: raise ValueError("O áudio pode ter no máximo dois minutos.")
                    chunks.append(converted.to_ndarray().flatten())
        if not count: raise ValueError()
        return np.concatenate(chunks).astype(np.float32)/32768, count/16000
    except ValueError as exc:
        raise ValueError(str(exc) or "Não foi possível ler o áudio.") from None
    except Exception:
        raise ValueError("Não foi possível ler o áudio. Envie WAV, MP3, M4A, OGG ou WebM.") from None


def transcribe(data):
    if not _slot.acquire(blocking=False):
        raise ValueError("Há outro áudio sendo transcrito. Aguarde alguns instantes.")
    started = time.monotonic(); seconds = None; status = "failed"
    try:
        samples, seconds = decode(data)
        segments, _ = model().transcribe(samples, language=os.getenv("LUMI_AUDIO_LANGUAGE", "pt"),
            beam_size=1, vad_filter=True, condition_on_previous_text=False)
        text = " ".join(segment.text.strip() for segment in segments if segment.no_speech_prob < 0.7).strip()
        if not text: raise ValueError("Não consegui identificar fala nesse áudio. Tente novamente ou envie por texto.")
        if len(text) > 8000: raise ValueError("A transcrição ficou muito longa. Divida o áudio em partes menores.")
        status = "completed"
        return text, seconds
    finally:
        try:
            record("faster-whisper-local", os.getenv("LUMI_AUDIO_MODEL", "base"), status,
                   round((time.monotonic()-started)*1000), audio_seconds=seconds)
        finally:
            _slot.release()
