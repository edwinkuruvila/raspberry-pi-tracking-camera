"""Latest-frame RTSP capture with automatic reconnection."""

import logging
import threading
import time

import cv2
import numpy as np

# FFmpeg keeps probing the low-frame-rate MJPEG stream until this deadline even
# though decoded frames are already available. One second is long enough for
# the loopback RTSP handshake and avoids making every activation wait five.
OPEN_TIMEOUT_MS = 1_000
READ_TIMEOUT_MS = 3_000
logger = logging.getLogger("uvicorn.error.roomcam.detection.capture")


class LatestFrameCapture:
    """Continuously reconnect to RTSP and expose only the newest decoded frame.

    Inference can occasionally take longer than one camera interval. Replacing a
    single frame slot prevents an old-frame queue from accumulating latency.
    """

    def __init__(self, source: str) -> None:
        self._source = source
        self._condition = threading.Condition()
        self._frame: np.ndarray | None = None
        self._sequence = 0
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            name="detection-capture",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._thread.join(timeout=READ_TIMEOUT_MS / 1_000 + 1)
        if self._thread.is_alive():
            logger.error("Detection capture thread did not stop within its read timeout")

    def wait_for_frame(
        self,
        sequence: int,
        timeout: float,
    ) -> tuple[int, np.ndarray] | None:
        with self._condition:
            available = self._condition.wait_for(
                lambda: self._closed or self._sequence > sequence,
                timeout=timeout,
            )
            if not available or self._closed or self._frame is None:
                return None
            return self._sequence, self._frame

    def _run(self) -> None:
        while not self._is_closed():
            capture = cv2.VideoCapture(
                self._source,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    OPEN_TIMEOUT_MS,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    READ_TIMEOUT_MS,
                ],
            )
            if not capture.isOpened():
                capture.release()
                time.sleep(0.5)
                continue

            logger.info("Connected to detection camera")
            try:
                while not self._is_closed():
                    received, frame = capture.read()
                    if not received:
                        logger.warning("Detection camera stopped delivering frames; reconnecting")
                        break
                    with self._condition:
                        self._frame = frame
                        self._sequence += 1
                        self._condition.notify_all()
            finally:
                capture.release()

            time.sleep(0.25)

    def _is_closed(self) -> bool:
        with self._condition:
            return self._closed
