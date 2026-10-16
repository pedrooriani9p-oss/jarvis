"""Escuta de "Hey Jarvis" / "Ei Jarvis" em segundo plano, 100% offline (openWakeWord).

O áudio do microfone é analisado só aqui no PC por um modelo pequeno treinado
para essa frase: nada é gravado nem enviado. Quando ouve, chama `on_wake()`;
a ponte então traz a janela do Jarvis para frente e avisa o site.
"""
import os
import sys
import threading
import time

WAKE_MODEL = "hey_jarvis_v0.1"
FRAME = 1280          # 80 ms a 16 kHz, o tamanho que o openWakeWord espera
THRESHOLD = 0.5


def models_dir():
    # no .exe os modelos vão empacotados junto (PyInstaller --add-data)
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "oww_models")
    import openwakeword
    return os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")


def make_model():
    from openwakeword.model import Model
    d = models_dir()
    return Model(
        wakeword_models=[os.path.join(d, WAKE_MODEL + ".onnx")],
        inference_framework="onnx",
        melspec_model_path=os.path.join(d, "melspectrogram.onnx"),
        embedding_model_path=os.path.join(d, "embedding_model.onnx"),
    )


class Detector:
    """Recebe quadros de áudio int16 e diz quando a frase de ativação apareceu."""

    def __init__(self, model, cooldown=2.5):
        self.model = model
        self.cooldown = cooldown
        self.last = float("-inf")

    def feed(self, frame, now=None):
        now = time.time() if now is None else now
        score = max(self.model.predict(frame).values())
        if score >= THRESHOLD and now - self.last > self.cooldown:
            self.last = now
            self.model.reset()
            return True
        return False


class Escuta:
    def __init__(self, on_wake, log=print):
        self.on_wake = on_wake
        self.log = log
        self.enabled = True
        self.status = "iniciando"

    def start(self):
        threading.Thread(target=self._run_forever, daemon=True).start()

    def _run_forever(self):
        while True:
            try:
                self._run()
            except Exception as e:  # microfone desconectado etc.: tenta de novo
                self.status = f"erro: {e}"[:150]
                self.log(self.status)
                time.sleep(10)

    def _run(self):
        import numpy as np
        import sounddevice as sd

        det = Detector(make_model())
        with sd.InputStream(samplerate=16000, blocksize=FRAME, dtype="int16", channels=1) as stream:
            self.status = "ouvindo"
            while True:
                data, _ = stream.read(FRAME)
                if self.enabled and det.feed(np.asarray(data[:, 0], dtype=np.int16)):
                    self.on_wake()
