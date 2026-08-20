"""LiteRT model input preparation and person inference."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from ai_edge_litert.interpreter import Interpreter

from .tracking import Detection
from .types import InterpreterProtocol

PERSON_CLASS_ID = 0


@dataclass(frozen=True, slots=True)
class ModelRuntime:
    interpreter: InterpreterProtocol
    input_detail: dict[str, Any]
    output_details: list[dict[str, Any]]


def load_model(model_path: Path, threads: int) -> ModelRuntime:
    interpreter = Interpreter(model_path=str(model_path), num_threads=threads)
    interpreter.allocate_tensors()
    return ModelRuntime(
        interpreter=interpreter,
        input_detail=interpreter.get_input_details()[0],
        output_details=interpreter.get_output_details(),
    )


def quantize_input(image: np.ndarray, input_detail: dict[str, Any]) -> np.ndarray:
    """Convert RGB pixels into the numeric representation required by the model."""

    dtype = input_detail["dtype"]
    if dtype == np.uint8:
        return image.astype(np.uint8)
    if dtype == np.int8:
        scale, zero_point = input_detail["quantization"]
        quantized = np.rint(image.astype(np.float32) / scale + zero_point)
        return np.clip(quantized, -128, 127).astype(np.int8)
    return image.astype(np.float32) / 255.0


def dequantize_output(tensor: np.ndarray, detail: dict[str, Any]) -> np.ndarray:
    """Convert quantized model output back to ordinary floating-point values."""

    scale, zero_point = detail["quantization"]
    if scale:
        return (tensor.astype(np.float32) - zero_point) * scale
    return tensor.astype(np.float32)


def find_people(
    interpreter: InterpreterProtocol,
    input_detail: dict[str, Any],
    output_details: list[dict[str, Any]],
    frame: np.ndarray,
    confidence_threshold: float,
) -> list[Detection]:
    """Run one inference and return normalized person boxes above the threshold."""

    _, input_height, input_width, _ = input_detail["shape"]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(
        rgb,
        (int(input_width), int(input_height)),
        interpolation=cv2.INTER_AREA,
    )
    model_input = np.expand_dims(quantize_input(resized, input_detail), axis=0)
    interpreter.set_tensor(input_detail["index"], model_input)
    interpreter.invoke()

    boxes, classes, scores, detection_count = [
        dequantize_output(
            interpreter.get_tensor(detail["index"]),
            detail,
        ).squeeze()
        for detail in output_details
    ]
    count = int(detection_count)
    if boxes.ndim != 2 or boxes.shape[-1] != 4:
        raise RuntimeError("Unexpected SSD MobileNet output tensors")

    people: list[Detection] = []
    for box, class_id, confidence in zip(
        boxes[:count],
        classes[:count],
        scores[:count],
        strict=True,
    ):
        if int(class_id) != PERSON_CLASS_ID or confidence < confidence_threshold:
            continue
        top, left, bottom, right = np.clip(box, 0, 1)
        people.append(
            Detection(
                confidence=round(float(confidence), 3),
                left=round(float(left), 4),
                top=round(float(top), 4),
                width=round(float(right - left), 4),
                height=round(float(bottom - top), 4),
            )
        )
    return people
