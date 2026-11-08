"""PaddleOCR 3.x 适配：每个 run 只创建一次引擎。"""
from pathlib import Path
import os

from ..contracts import OcrBox


def configure_cache():
    root = Path(__file__).resolve().parents[2]
    for key, folder in {"PADDLE_PDX_CACHE_HOME": "paddlex", "PADDLE_HOME": "paddle",
                        "PADDLEOCR_HOME": "paddleocr", "HF_HOME": "huggingface"}.items():
        os.environ.setdefault(key, str(root / ".cache" / folder))
    os.environ.setdefault("XDG_CACHE_HOME", str(root / ".cache"))


class OcrEngine:
    def __init__(self, config):
        configure_cache()
        from paddleocr import PaddleOCR
        self.engine = PaddleOCR(
            text_detection_model_name=config.det_model,
            text_recognition_model_name=config.rec_model,
            text_rec_score_thresh=config.score_min,
            use_doc_orientation_classify=False, use_doc_unwarping=False,
            use_textline_orientation=False, device="cpu",
            cpu_threads=config.cpu_threads, enable_mkldnn=False,
        )

    def recognize(self, image, *, frame, ts, call):
        result = list(self.engine.predict(image))[0]
        return [OcrBox(text=text, score=float(score), poly=poly.tolist(),
                       frame=frame, ts=ts, ocr_call=call)
                for text, score, poly in zip(result["rec_texts"], result["rec_scores"], result["rec_polys"], strict=True)]
