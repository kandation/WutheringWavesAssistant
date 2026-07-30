import logging

import numpy as np
from tqdm import tqdm
from src.core.i18n import Language
from src.util import file_util, img_util

logger = logging.getLogger(__name__)

# https://github.com/RapidAI/RapidOCR
# https://paddlepaddle.github.io/PaddleOCR/latest/model/index.html

from importlib.metadata import version
from packaging.version import Version

# det 找出文本框位置
# rec 识别具体内容，根据det文本框的位置裁剪出文本图片，识别出具体文字
# cls 判断文字方向

_rapidocr_version = Version(version("rapidocr"))
if _rapidocr_version < Version("3.0.0"):
    from rapidocr import RapidOCR, VisRes
    # from rapidocr.utils import RapidOCROutput  # v2.0.6

    _COMMON_PARAMS = {
        "Global.use_cls": False,
        "Global.width_height_ratio": -1,
        "Det.limit_type": "min",
        "Det.limit_side_len": 0,
    }
    _CPU_PARAMS = {
        **_COMMON_PARAMS,
    }
    _DML_PARAMS = {
        **_COMMON_PARAMS,
        "Global.with_onnx": True,
        "EngineConfig.onnxruntime.use_dml": True,
    }
    # _GPU_ONNXRUNTIME_PARAMS = {
    #     **_COMMON_PARAMS,
    #     "Global.with_onnx": True,
    #     "EngineConfig.onnxruntime.use_cuda": True,
    # }
    _GPU_PADDLEPADDLE_PARAMS = {
        **_COMMON_PARAMS,
        "Global.with_paddle": True,
        "EngineConfig.paddle.use_cuda": True,
    }
else:
    from rapidocr import RapidOCR, VisRes, EngineType
    # from rapidocr.utils.output import RapidOCROutput  # v3.5.0

    _COMMON_PARAMS = {
        # # 如果输入图像的最大边大于 max_side_len，则会按宽高比，将最大边缩放到 max_side_len。默认为 2000 px
        # "Global.max_side_len": 2560,
        # # 如果输入图像的最小边小于 min_side_len，则会按宽高比，将最小边缩放到 min_side_len。默认为 30 px
        # "Global.min_side_len": 30,
        "Global.use_cls": False,
        "Global.width_height_ratio": -1,
        "Global.log_level": "error",  # debug / info / warning / error / critical
        # 限制图像的最小边长度还是最大边为 limit_side_len。
        # 示例解释：当 limit_type=min 和 limit_side_len=736 时，
        # 图像最小边小于 736 时，会将图像最小边拉伸到 736，另一边则按图像原始比例等比缩放。取值范围为：[min, max]，默认值为 min
        "Det.limit_type": "min",
        "Det.limit_side_len": 0,
    }
    _CPU_PARAMS = {
        **_COMMON_PARAMS,
    }
    _DML_PARAMS = {
        **_COMMON_PARAMS,
        "EngineConfig.onnxruntime.use_dml": True,
    }
    # _GPU_ONNXRUNTIME_PARAMS = {
    #     **_COMMON_PARAMS,
    #     "EngineConfig.onnxruntime.use_cuda": True,
    # }
    _GPU_PADDLEPADDLE_PARAMS = {
        **_COMMON_PARAMS,
        "EngineConfig.paddle.use_cuda": True,
        "Det.engine_type": EngineType.PADDLE,
        "Cls.engine_type": EngineType.PADDLE,
        "Rec.engine_type": EngineType.PADDLE,
    }


def _ocr_params(*, use_gpu: bool, use_dml: bool) -> dict:
    if use_gpu:
        return dict(_GPU_PADDLEPADDLE_PARAMS)
    if use_dml:
        return dict(_DML_PARAMS)
    return dict(_CPU_PARAMS)


def _apply_rec_lang(params: dict, game_lang: Language | None) -> None:
    """Switch recognition model for non-Chinese game clients (RapidOCR >= 3.4)."""
    if game_lang != Language.TH or _rapidocr_version < Version("3.4.0"):
        return
    from rapidocr import LangRec, ModelType, OCRVersion

    params.update({
        "Rec.lang_type": LangRec.TH,
        "Rec.model_type": ModelType.MOBILE,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
    })
    logger.info("OCR recognition model: Thai (PP-OCRv5)")


def create_ocr(*, use_gpu: bool = False, use_dml=False, game_lang: Language | None = None) -> RapidOCR:
    # https://rapidai.github.io/RapidOCRDocs/main/install_usage/rapidocr/API/RapidOCR/#_1
    params = _ocr_params(use_gpu=use_gpu, use_dml=use_dml)
    _apply_rec_lang(params, game_lang)
    engine = RapidOCR(
        params=params
    )  # 输入BGR
    # logger.debug(engine.text_det.session.session.get_provider_options())
    # sss = engine.text_det.session.session
    # logger.debug(engine.text_det.session.session.get_session_options())
    return engine


# https://github.com/microsoft/onnxruntime/issues/13198#issuecomment-1554180044
def model_warmup(engine: RapidOCR, batch_size: int = 1, min_size: int = 10, max_size: int = 20):
    """
    onnxruntime-gpu
    Recognition model have input size: [-1, 3, 48, -1]
    ONNXRuntime with CUDA support is not performing well with arbitrary input size
    So we need to warmup the model with arbitrary input size
    """
    logger.info("Warming up model...")
    img_names = ["Dialogue_001.png", "Login_001.png", "Revival_001.png"]
    imgs = [img_util.read_img(file_util.get_assets_screenshot(img_name)) for img_name in img_names]
    index = 0
    for i in tqdm(range(min_size, max_size), desc="Warming up model"):
        engine(imgs[index % 3], use_det=True, use_rec=True, use_cls=False)
        index += 1
    logger.info("Model warmup completed")


def print_ocr_result(output):
    for i in range(output.boxes.shape[0]):
        logger.debug("score: %s,\ttext: '%s',\tbox: %s", output.scores[i], output.txts[i], list(output.boxes[i]))


def draw_ocr_result(output) -> np.ndarray:
    if output.boxes is None:
        return output.img
    vis = VisRes()
    if output.word_results and any(output.word_results):
        words, words_scores, words_boxes = zip(*output.word_results)
        vis_img = vis(output.img, words_boxes, words, words_scores)
    else:
        vis_img = vis(output.img, output.boxes, output.txts, output.scores)
    return vis_img

# def draw_detections(img: np.ndarray, boxes: Sequence, scores: Sequence, classes: Sequence):
#     # Generate a color palette for the classes
#     color_palette = np.random.uniform(0, 255, size=(len(classes), 3))
#     for i in range(len(boxes)):
#         box, score, class_id = boxes[i], scores[i], classes[i]
#         # Extract the coordinates of the bounding box
#         x1, y1, x2, y2 = int(box[0][0]), int(box[0][1]), int(box[2][0]), int(box[2][1])
#         # Retrieve the color for the class ID
#         color = color_palette[i]
#         # Draw the bounding box on the image
#         cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
#         # cv2.rectangle(img, (int(box[0][0]), int(box[0][1])), (int(box[2][0]), int(box[2][1])), color, 2)
#         # Create the label text with class name and score
#         label = f"{class_id}: {score:.2f}"
#         # Calculate the dimensions of the label text
#         (label_width, label_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
#         # Calculate the position of the label text
#         label_x = x1
#         label_y = y1 - 10 if y1 - 10 > label_height else y1 + 10
#         # Draw a filled rectangle as the background for the label text
#         logger.debug(label_x)
#         logger.debug((label_x, label_y - label_height))
#         logger.debug((label_x + label_width, label_y + label_height))
#         cv2.rectangle(img, (label_x, label_y - label_height), (label_x + label_width, label_y + label_height), color, cv2.FILLED)
#         # Draw the label text on the image
#         cv2.putText(img, label, (label_x, label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
