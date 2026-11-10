"""Child-process entry: optional dependencies never load into the acquisition worker."""

import hashlib
import importlib
import json
import sys
from importlib.metadata import version
from pathlib import Path


def main() -> None:
    media, model = Path(sys.argv[1]), Path(sys.argv[2])
    maximum = int(sys.argv[3])
    manifest = json.loads((model / "insight-model.json").read_bytes())
    files = manifest["files"]
    if not {"model.bin", "config.json", "tokenizer.json"}.issubset(files):
        raise ValueError("Incomplete ASR bundle")
    for name, expected in files.items():
        if Path(name).name != name:
            raise ValueError("Invalid ASR model asset path")
        with (model / name).open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != expected:
                raise ValueError("ASR model bytes changed")
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    if manifest["model_sha256"] != digest or digest != sys.argv[4]:
        raise ValueError("ASR bundle differs from the frozen plan")
    av = importlib.import_module("av")
    np = importlib.import_module("numpy")
    whisper = importlib.import_module("faster_whisper")
    samples = []
    count = 0
    with av.open(str(media)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                array = converted.to_ndarray().flatten()
                count += len(array)
                if count > maximum * 16000:
                    raise ValueError("Audio duration exceeds declared ceiling")
                samples.append(array)
        for converted in resampler.resample(None):
            array = converted.to_ndarray().flatten()
            count += len(array)
            if count > maximum * 16000:
                raise ValueError("Audio duration exceeds declared ceiling")
            samples.append(array)
    if not samples:
        raise ValueError("No audio samples")
    audio = np.concatenate(samples).astype(np.float32) / 32768.0
    engine = whisper.WhisperModel(
        str(model),
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        num_workers=1,
        local_files_only=True,
    )
    segments, info = engine.transcribe(
        audio,
        beam_size=1,
        condition_on_previous_text=False,
        language="en" if manifest["model"].endswith(".en") else None,
    )
    duration = count / 16000
    rows = [
        dict(
            start=float(max(0, s.start)),
            duration=float(min(s.end, duration) - max(0, s.start)),
            text=s.text.strip(),
        )
        for s in segments
        if s.text.strip() and min(s.end, duration) > max(0, s.start)
    ]
    print(
        json.dumps(
            dict(
                schema="youtube-transcript@1",
                retrieval="local_asr",
                language=info.language,
                is_generated=True,
                segments=rows,
                model=manifest["model"],
                model_sha256=digest,
                engine="faster-whisper@" + version("faster-whisper"),
                audio_duration_seconds=count / 16000,
                limitations=[
                    "Locally generated ASR; names, numbers and timestamps require source review; not author-provided captions"
                ],
            )
        )
    )


if __name__ == "__main__":
    main()
