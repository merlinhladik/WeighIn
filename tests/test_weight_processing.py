import asyncio
import json

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
    d0 = _digit_image_for_pattern((1, 1, 1, 0, 1, 1, 1))
    d8 = _digit_image_for_pattern((1, 1, 1, 1, 1, 1, 1))

    assert weight.decode_7seg_digit(d0) == 0
    assert weight.decode_7seg_digit(d8) == 8


def test_auto_digit_boxes_from_mask_returns_boxes():
    mask = np.zeros((200, 300), dtype=np.uint8)
    mask[40:120, 20:40] = 255
    mask[40:120, 80:100] = 255
    mask[40:120, 140:160] = 255

    boxes = weight.auto_digit_boxes_from_mask(mask)

    assert boxes is not None
    assert len(boxes) == 3


def test_decode_from_fixed_boxes_aggregates_digits(monkeypatch):
    mask = np.ones((200, 300), dtype=np.uint8) * 255
    boxes = [(10, 10, 40, 80), (60, 10, 40, 80), (110, 10, 40, 80)]
    seq = iter([1, 2, 3])

    monkeypatch.setattr(weight, "decode_7seg_digit", lambda _img: next(seq))

    text, digits = weight.decode_from_fixed_boxes(mask, boxes)

    assert text == "123"
    assert digits == [1, 2, 3]


def test_decode_7seg_digit_handles_empty_and_too_small():
    assert weight.decode_7seg_digit(None) is None
    assert weight.decode_7seg_digit(np.array([], dtype=np.uint8)) is None
    assert weight.decode_7seg_digit(np.zeros((10, 5), dtype=np.uint8)) is None


def test_decode_7seg_digit_handles_empty_segment_slices():
    class FakeBinDigit:
        size = 1
        shape = (30, 20)

        def __getitem__(self, _key):
            return np.array([], dtype=np.uint8)

    assert weight.decode_7seg_digit(FakeBinDigit()) is None


def test_auto_digit_boxes_from_mask_returns_none_when_too_few():
    mask = np.zeros((120, 120), dtype=np.uint8)
    mask[20:40, 20:40] = 255
    boxes = weight.auto_digit_boxes_from_mask(mask)
    assert boxes is None


def test_auto_digit_boxes_from_mask_limits_max_digits():
    mask = np.zeros((220, 600), dtype=np.uint8)
    for i in range(6):
        x = 10 + i * 80
        mask[40:120, x : x + 20] = 255

    boxes = weight.auto_digit_boxes_from_mask(mask)
    assert boxes is not None
    assert len(boxes) == weight.MAX_DIGITS


def test_decode_from_fixed_boxes_returns_none_on_failed_digit(monkeypatch):
    mask = np.ones((200, 300), dtype=np.uint8) * 255
    boxes = [(10, 10, 40, 80), (60, 10, 40, 80)]
    monkeypatch.setattr(weight, "decode_7seg_digit", lambda _img: None)

    text, digits = weight.decode_from_fixed_boxes(mask, boxes)

    assert text is None
    assert digits == [None, None]


def test_decode_from_fixed_boxes_handles_empty_cropped_digit():
    mask = np.ones((20, 20), dtype=np.uint8) * 255
    boxes = [(200, 200, 10, 10)]

    text, digits = weight.decode_from_fixed_boxes(mask, boxes)

    assert text is None
    assert digits == [None]


def test_send_weight_sends_expected_payload(monkeypatch):
    captured = {}

    class FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send(self, msg):
            captured["msg"] = msg

    monkeypatch.setattr(weight.websockets, "connect", lambda _url: FakeConn())
    import asyncio

    asyncio.run(weight.send_weight("7564"))
    assert '"type": "weight"' in captured["msg"]
    assert '"weight": "7564"' in captured["msg"]


def test_run_weight_scanner_raises_when_camera_not_open(monkeypatch):
    class ClosedCap:
        def set(self, *_args):
            return None

        def isOpened(self):
            return False

    monkeypatch.setattr(weight.cv2, "VideoCapture", lambda _idx: ClosedCap())
    with pytest.raises(RuntimeError, match="Webcam"):
        weight.run_weight_scanner(0)


def test_run_weight_scanner_quit_releases_resources(monkeypatch):
    calls = {"release": 0, "destroy": 0, "loop": 0}

    class Cap:
        def set(self, *_args):
            return None

        def isOpened(self):
            return True

        def release(self):
            calls["release"] += 1

    async def fake_loop(_cap):
        calls["loop"] += 1

    monkeypatch.setattr(weight.cv2, "VideoCapture", lambda _idx: Cap())
    monkeypatch.setattr(weight, "_run_weight_scanner_loop", fake_loop)
    monkeypatch.setattr(weight.cv2, "destroyAllWindows", lambda: calls.__setitem__("destroy", calls["destroy"] + 1))

    weight.run_weight_scanner(0)

    assert calls["release"] == 1
    assert calls["destroy"] == 1
    assert calls["loop"] == 1


def test_run_weight_scanner_request_uses_decoded_weight_and_sends(monkeypatch):
    sent = []

    class Cap:
        def __init__(self):
            self.i = 0

        def set(self, *_args):
            return None

        def isOpened(self):
            return True

        def read(self):
            self.i += 1
            if self.i <= 2:
                return True, np.zeros((50, 50, 3), dtype=np.uint8)
            return False, None

        def release(self):
            return None

    class FakeWS:
        def __init__(self):
            self.messages = [json.dumps({"type": "REQUEST_WEIGHT"})]

        async def recv(self):
            if self.messages:
                return self.messages.pop(0)
            await asyncio.sleep(1)
            return ""

    class FakeConn:
        async def __aenter__(self):
            return FakeWS()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    keys = iter([0, ord("q")])

    monkeypatch.setattr(weight.cv2, "waitKey", lambda _delay: next(keys))
    monkeypatch.setattr(weight.cv2, "imshow", lambda *_args: None)
    monkeypatch.setattr(weight.cv2, "destroyAllWindows", lambda: None)
    monkeypatch.setattr(weight.websockets, "connect", lambda _url: FakeConn())
    monkeypatch.setattr(weight, "_decode_current_weight", lambda _frame, _boxes: ("123", [1, 2, 3], _boxes))

    async def fake_send_weight(txt, websocket=None):
        sent.append((txt, websocket is not None))

    monkeypatch.setattr(weight, "send_weight", fake_send_weight)

    asyncio.run(weight._run_weight_scanner_loop(Cap()))

    assert sent == [("123", True)]


def test_run_weight_scanner_request_without_boxes_prints_and_continues(monkeypatch):
    prints = []

    class Cap:
        def __init__(self):
            self.i = 0

        def set(self, *_args):
            return None

        def isOpened(self):
            return True

        def read(self):
            self.i += 1
            if self.i <= 2:
                return True, np.zeros((50, 50, 3), dtype=np.uint8)
            return False, None

        def release(self):
            return None

    class FakeWS:
        def __init__(self):
            self.messages = [json.dumps({"type": "REQUEST_WEIGHT"})]

        async def recv(self):
            if self.messages:
                return self.messages.pop(0)
            await asyncio.sleep(1)
            return ""

    class FakeConn:
        async def __aenter__(self):
            return FakeWS()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    keys = iter([0, ord("q")])

    monkeypatch.setattr(weight.cv2, "waitKey", lambda _delay: next(keys))
    monkeypatch.setattr(weight.cv2, "imshow", lambda *_args: None)
    monkeypatch.setattr(weight.cv2, "destroyAllWindows", lambda: None)
    monkeypatch.setattr(weight.websockets, "connect", lambda _url: FakeConn())
    monkeypatch.setattr(weight, "_decode_current_weight", lambda _frame, _boxes: (None, [], _boxes))
    monkeypatch.setattr("builtins.print", lambda msg: prints.append(str(msg)))

    asyncio.run(weight._run_weight_scanner_loop(Cap()))

    assert any("Konnte nicht sicher decodieren" in msg for msg in prints)


def test_run_weight_scanner_prints_failed_digits_when_decode_returns_none(monkeypatch):
    prints = []

    class Cap:
        def __init__(self):
            self.i = 0

        def set(self, *_args):
            return None

        def isOpened(self):
            return True

        def read(self):
            self.i += 1
            if self.i <= 2:
                return True, np.zeros((50, 50, 3), dtype=np.uint8)
            return False, None

        def release(self):
            return None

    class FakeWS:
        def __init__(self):
            self.messages = [json.dumps({"type": "REQUEST_WEIGHT"})]

        async def recv(self):
            if self.messages:
                return self.messages.pop(0)
            await asyncio.sleep(1)
            return ""

    class FakeConn:
        async def __aenter__(self):
            return FakeWS()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    keys = iter([0, ord("q")])
    monkeypatch.setattr(weight.cv2, "waitKey", lambda _delay: next(keys))
    monkeypatch.setattr(weight.cv2, "imshow", lambda *_args: None)
    monkeypatch.setattr(weight.cv2, "destroyAllWindows", lambda: None)
    monkeypatch.setattr(weight.websockets, "connect", lambda _url: FakeConn())
    monkeypatch.setattr(weight, "_decode_current_weight", lambda _frame, _boxes: (None, [1, None, 3], _boxes))
    monkeypatch.setattr("builtins.print", lambda msg: prints.append(str(msg)))

    asyncio.run(weight._run_weight_scanner_loop(Cap()))

    assert any("Fehler bei Ziffer(n): [2]" in msg for msg in prints)
