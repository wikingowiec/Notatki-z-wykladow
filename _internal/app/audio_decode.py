"""Dekodowanie audio (m4a, mp3, wideo…) do 16 kHz mono – zgodne ze starymi i nowymi wersjami PyAV.

faster-whisper 1.2 woła av.open(…, metadata_errors="ignore"), a nowsze PyAV tej opcji już nie znają
(„open() got an unexpected keyword argument 'metadata_errors'”). Tu próbujemy z nią, a gdy jej nie ma – bez niej.
Uszkodzone ramki i brakujące metadane są pomijane."""
from __future__ import annotations

import gc
import io
import logging

import numpy as np

log = logging.getLogger(__name__)


def _open(src):
    import av
    try:
        return av.open(src, mode="r", metadata_errors="ignore")
    except TypeError:
        return av.open(src, mode="r")


def decode_audio(input_file, sampling_rate: int = 16000, split_stereo: bool = False):
    import av
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="stereo" if split_stereo else "mono",
                                                  rate=sampling_rate)
    buf = io.BytesIO()
    dtype = None
    with _open(input_file) as container:
        if not container.streams.audio:
            raise RuntimeError("W tym pliku nie ma ścieżki dźwiękowej.")
        stream = container.streams.audio[0]
        for packet in container.demux(stream):
            try:
                frames = packet.decode()
            except Exception:  # noqa: BLE001 – uszkodzony fragment: pomiń
                continue
            for frame in frames:
                try:
                    out = resampler.resample(frame)
                except Exception:  # noqa: BLE001
                    continue
                for f in (out if isinstance(out, list) else [out]):
                    arr = f.to_ndarray()
                    dtype = arr.dtype
                    buf.write(arr.tobytes())
        try:
            for f in resampler.resample(None) or []:
                arr = f.to_ndarray()
                dtype = arr.dtype
                buf.write(arr.tobytes())
        except Exception:  # noqa: BLE001
            pass
    del resampler
    gc.collect()
    audio = np.frombuffer(buf.getbuffer(), dtype=dtype or np.int16).astype(np.float32) / 32768.0
    if split_stereo:
        return audio[0::2], audio[1::2]
    return audio


def patch_faster_whisper() -> None:
    """Podmienia dekodowanie w faster-whisper na wersję zgodną z każdym PyAV."""
    try:
        import faster_whisper.audio as fa
        fa.decode_audio = decode_audio
        import faster_whisper.transcribe as ft
        if hasattr(ft, "decode_audio"):
            ft.decode_audio = decode_audio
        import faster_whisper as fw
        if hasattr(fw, "decode_audio"):
            fw.decode_audio = decode_audio
    except Exception as e:  # noqa: BLE001
        log.warning("faster-whisper: %s", e)
