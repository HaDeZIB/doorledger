import asyncio

import numpy as np

from doorledger.privacy import apply_privacy_zones, privacy_zones_from_configurations

ZONE = {"id": "z1", "vertices": [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.0},
                                 {"x": 0.5, "y": 0.5}, {"x": 0.0, "y": 0.5}]}


def test_zone_is_blacked_out_and_rest_untouched():
    img = np.full((100, 200, 3), 200, np.uint8)
    out = apply_privacy_zones(img, [ZONE])
    assert out[10, 10].tolist() == [0, 0, 0]          # inside the zone
    assert out[90, 190].tolist() == [200, 200, 200]   # outside
    assert img[10, 10].tolist() == [200, 200, 200]    # input not mutated


def test_no_zones_returns_same_image():
    img = np.zeros((10, 10, 3), np.uint8)
    assert apply_privacy_zones(img, []) is img


def test_zones_from_configurations_shape():
    cfg = {"image_enhancements": {"privacy_zones": [ZONE]}}
    assert privacy_zones_from_configurations(cfg) == [ZONE]
    assert privacy_zones_from_configurations({}) == []
    assert privacy_zones_from_configurations(None) == []


def test_live_skips_e2ee_device(monkeypatch):
    from doorledger.live import LiveController

    class Dev:
        id, name, online = "d1", "Front", True
        configurations = {"e2e_encryption": {"enabled": True},
                          "image_enhancements": {"privacy_zones": [ZONE]}}
        is_encrypted = True

    class Ring:
        async def devices(self):
            return [Dev()]

    class Eng:
        device: dict = {}

    ctl = LiveController.__new__(LiveController)
    ctl.engine = Eng()
    assert asyncio.run(ctl._prepare_device(Ring())) is None
    assert ctl.engine.device["encrypted"] is True
    assert ctl.engine.device["privacy_zones"] == [ZONE]
