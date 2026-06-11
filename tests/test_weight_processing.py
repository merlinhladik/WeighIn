import asyncio

import numpy as np
import pytest

import weight


def _digit_image_for_pattern(pattern):
    h, w = 140, 80
    img = np.zeros((h, w), dtype=np.uint8)

    regions = [
        (int(w * 0.30), int(h * 0.00), int(w * 0.70), int(h * 0.20)),
        (0, int(h * 0.20), int(w * 0.50), int(h * 0.40)),
        (int(w * 0.50), int(h * 0.20), w, int(h * 0.40)),
        (int(w * 0.30), int(h * 0.40), int(w * 0.70), int(h * 0.62)),
        (0, int(h * 0.60), int(w * 0.50), int(h * 0.80)),
        (int(w * 0.50), int(h * 0.60), w, int(h * 0.80)),
        (0, int(h * 0.80), w, h),
    ]

    for enabled, (x1, y1, x2, y2) in zip(pattern, regions):
        if enabled:
            img[y1:y2, x1:x2] = 255

    return img


def test_red_mask_detects_red_region():
    bgr = np.zeros((40, 40, 3), dtype=np.uint8)
    bgr[10:30, 10:30] = [0, 0, 255]

    mask = weight.red_mask(bgr)

    assert mask.shape == (40, 40)
    assert int(mask.max()) == 255


def test_decode_7seg_digit_for_0_and_8():
    assert weight.decode_7seg_digit(_digit_image_for_pattern((1, 1, 1, 0, 1, 1, 1))) == 0
    assert weight.decode_7seg_digit(_digit_image_for_pattern((1, 1, 1, 1, 1, 1, 1))) == 8


def test_decode_7seg_digit_handles_empty_and_small_inputs():
    assert weight.decode_7seg_digit(None) is None
    assert weight.decode_7seg_digit(np.array([], dtype=np.uint8)) is None
    assert weight.decode_7seg_digit(np.zeros((10, 5), dtype=np.uint8)) is None


def test_auto_digit_boxes_from_mask_returns_boxes():
    mask = np.zeros((200, 300), dtype=np.uint8)
    mask[40:120, 20:40] = 255
    mask[40:120, 80:100] = 255
    mask[40:120, 140:160] = 255

    boxes = weight.auto_digit_boxes_from_mask(mask)

    assert boxes is not None
    assert len(boxes) == 3


def test_auto_digit_boxes_from_mask_returns_none_when_too_few():
    mask = np.zeros((120, 120), dtype=np.uint8)
    mask[20:40, 20:40] = 255

    assert weight.auto_digit_boxes_from_mask(mask) is None


def test_decode_from_fixed_boxes_aggregates_digits(monkeypatch):
    mask = np.ones((200, 300), dtype=np.uint8) * 255
    boxes = [(10, 10, 40, 80), (60, 10, 40, 80), (110, 10, 40, 80)]
    seq = iter([1, 2, 3])

    monkeypatch.setattr(weight, "decode_7seg_digit", lambda _img: next(seq))

    assert weight.decode_from_fixed_boxes(mask, boxes) == "123"


def test_decode_from_fixed_boxes_returns_none_on_failed_digit(monkeypatch):
    mask = np.ones((200, 300), dtype=np.uint8) * 255
    boxes = [(10, 10, 40, 80), (60, 10, 40, 80)]

    monkeypatch.setattr(weight, "decode_7seg_digit", lambda _img: None)

    assert weight.decode_from_fixed_boxes(mask, boxes) is None


def test__decode_current_weight_reuses_last_boxes(monkeypatch):
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    mask = np.ones((40, 40), dtype=np.uint8) * 255
    last_boxes = [(1, 2, 3, 4)]
    rectangles = []
    shown = []

    monkeypatch.setattr(weight, "red_mask", lambda _frame: mask)
    monkeypatch.setattr(weight, "auto_digit_boxes_from_mask", lambda _mask: None)
    monkeypatch.setattr(weight, "decode_from_fixed_boxes", lambda _mask, boxes: "456")
    monkeypatch.setattr(weight.cv2, "cvtColor", lambda _img, _code: np.zeros((40, 40, 3), dtype=np.uint8))
    monkeypatch.setattr(weight.cv2, "rectangle", lambda *args: rectangles.append(args[1:3]))
    monkeypatch.setattr(weight.cv2, "imshow", lambda name, img: shown.append((name, img.shape)))

    text, boxes = weight._decode_current_weight(frame, last_boxes)

    assert text == "456"
    assert boxes == last_boxes
    assert rectangles
    assert shown == [("debug", (40, 40, 3))]


def test_main_processes_request_weight_and_closes_resources(monkeypatch):
    class StopLoop(Exception):
        pass

    class DummyCap:
        def __init__(self):
            self.released = False

        def set(self, *_args):
            return None

        def isOpened(self):
            return True

        def read(self):
            return True, np.zeros((20, 20, 3), dtype=np.uint8)

        def release(self):
            self.released = True

    class DummyWS:
        instance = None

        def __init__(self, url):
            self.url = url
            self.connected = False
            self.closed = False
            DummyWS.instance = self

        async def connect(self):
            self.connected = True

        async def close(self):
            self.closed = True

        async def recv_json(self):
            return {"type": "REQUEST_WEIGHT"}

    class DummyWeightClient:
        seen = []

        def __init__(self, ws, weight_provider):
            self.ws = ws
            self.weight_provider = weight_provider

        async def handle_message(self, msg):
            DummyWeightClient.seen.append((msg, self.weight_provider()))
            raise StopLoop()

    cap = DummyCap()
    destroy_calls = []

    monkeypatch.setattr(weight.cv2, "VideoCapture", lambda _idx: cap)
    monkeypatch.setattr(weight.cv2, "imshow", lambda *_args: None)
    monkeypatch.setattr(weight.cv2, "waitKey", lambda _delay: 0)
    monkeypatch.setattr(weight.cv2, "destroyAllWindows", lambda: destroy_calls.append(True))
    monkeypatch.setattr(weight, "WebSocketClient", DummyWS)
    monkeypatch.setattr(weight, "WeightClient", DummyWeightClient)
    monkeypatch.setattr(weight, "_decode_current_weight", lambda _frame, last_boxes: ("321", last_boxes))
    monkeypatch.setattr(weight, "asyncio", asyncio, raising=False)

    with pytest.raises(StopLoop):
        asyncio.run(weight.main())

    assert DummyWS.instance.connected is True
    assert DummyWS.instance.closed is True
    assert DummyWeightClient.seen == [({"type": "REQUEST_WEIGHT"}, "321")]
    assert cap.released is True
    assert destroy_calls == [True]
