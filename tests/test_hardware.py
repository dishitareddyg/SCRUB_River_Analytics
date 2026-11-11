"""UART contract: exact STM32 parsing, exact motor packets, cadence, reliability."""

from __future__ import annotations

import json
import threading
import time
import unittest
from unittest import mock

from helpers import FakeSerial, override, stm32_packet

from config.settings import settings
from hardware import stm32 as stm32_mod
from hardware.gps import GPSWorker
from hardware.live_state import LiveState, PacketRouter
from hardware.motor_controller import MotorControllerWorker, MotorState
from hardware.protocol import build_motor_command, parse_stm32_packet
from hardware.stm32 import STM32Worker


class TestStm32Parser(unittest.TestCase):
    def test_exact_documented_packet(self):
        raw = json.loads(
            '{"device_id":"BOT001","timestamp":"2026-11-05T10:41:00.000Z","motors":{"left":120,"right":-80},'
            '"gps":{"latitude":12.91686,"longitude":77.48698},"compass":{"heading":182.4},'
            '"sensors":{"ph":7.12,"tds":214.2,"turbidity":15.3,"temperature_c":27.4,"humidity_percent":71.2}}'
        )
        p = parse_stm32_packet(raw)
        self.assertEqual(p.device_id, "BOT001")
        self.assertEqual(p.timestamp, "2026-11-05T10:41:00.000Z")
        self.assertEqual((p.motor_left, p.motor_right), (120.0, -80.0))
        self.assertEqual((p.latitude, p.longitude), (12.91686, 77.48698))
        self.assertAlmostEqual(p.heading, 182.4)
        self.assertEqual(p.sensors, {"ph": 7.12, "tds": 214.2, "turbidity": 15.3,
                                     "temperature_c": 27.4, "humidity_percent": 71.2})
        self.assertEqual(p.warnings, [])

    def test_null_and_invalid_values(self):
        p = parse_stm32_packet(stm32_packet(sensors={"ph": None, "tds": "NaN", "turbidity": True,
                                                     "temperature_c": "27.5", "humidity_percent": None}))
        self.assertEqual(p.sensors, {"ph": None, "tds": None, "turbidity": None,
                                     "temperature_c": 27.5, "humidity_percent": None})

    def test_gps_rejections(self):
        self.assertFalse(parse_stm32_packet(stm32_packet(lat=0.0, lon=0.0)).has_gps)  # no fix
        self.assertFalse(parse_stm32_packet(stm32_packet(lat=95.0)).has_gps)
        self.assertFalse(parse_stm32_packet(stm32_packet(lat=None)).has_gps)
        p = parse_stm32_packet({"device_id": "BOT001"})  # sections missing
        self.assertIsNotNone(p)
        self.assertFalse(p.has_gps)
        self.assertIn("missing_or_invalid_sensors", p.warnings)
        self.assertIsNone(parse_stm32_packet([1, 2]))

    def test_heading_normalised(self):
        self.assertAlmostEqual(parse_stm32_packet(stm32_packet(heading=-10)).heading, 350.0)
        with override(COMPASS_DECLINATION_DEG=-1.5):
            self.assertAlmostEqual(parse_stm32_packet(stm32_packet(heading=0.5)).heading, 359.0)

    def test_router_updates_live_state(self):
        gps, motor, live = GPSWorker(), MotorControllerWorker(), LiveState()
        PacketRouter(gps, motor, live).on_stm32_packet(stm32_packet(sensors={"ph": 20.0, "tds": 100}))
        snap = live.snapshot()
        self.assertIsNone(snap.readings["ph"])           # out of range -> NULL
        self.assertEqual(snap.readings["tds"], 100.0)
        self.assertIsNone(snap.readings["turbidity"])    # missing -> NULL
        self.assertEqual(snap.hardware_timestamp, "2026-11-05T10:41:00.000Z")
        self.assertTrue(gps.get_fix().valid)
        self.assertEqual(motor.get_state(), MotorState.IDLE)


class TestMotorPacket(unittest.TestCase):
    def test_exact_format(self):
        self.assertEqual(build_motor_command(100, 100), b'{"left":"+100","right":"+100","mode":"auto"}\n')
        self.assertEqual(build_motor_command(0, -50), b'{"left":"+0","right":"-50","mode":"auto"}\n')
        pkt = json.loads(build_motor_command(12, 34))
        self.assertEqual(list(pkt.keys()), ["left", "right", "mode"])

    def test_clamping(self):
        with override(MAX_MOTOR_POWER=300):
            self.assertEqual(json.loads(build_motor_command(5000, -5000)), {"left": "+300", "right": "-300", "mode": "auto"})
        self.assertEqual(json.loads(build_motor_command(5000, -5000, max_power=2000)),
                         {"left": "+999", "right": "-999", "mode": "auto"})  # hardware limit

    def test_default_frequencies_are_documented_values(self):
        self.assertEqual(settings.MOTOR_COMMAND_INTERVAL_S, 2.0)
        self.assertEqual(settings.STM32_PACKET_INTERVAL_S, 2.0)
        self.assertEqual(settings.SENSOR_STORE_INTERVAL_S, 10.0)
        self.assertEqual(settings.UPLOAD_INTERVAL_S, 10.0)

    def test_one_packet_per_interval(self):
        motor = MotorControllerWorker()
        ser = FakeSerial()
        motor.inject_serial(ser, threading.Lock())
        motor.set_desired(150, 105)
        with override(MOTOR_COMMAND_INTERVAL_S=0.2):
            motor.start()
            time.sleep(1.05)
            motor._stop_event.set()
            motor._thread.join()
        n = len(ser.writes)
        self.assertTrue(5 <= n <= 7, n)  # ~1 per 0.2 s, no bursts
        self.assertEqual(ser.packets()[0], {"left": "+150", "right": "+105", "mode": "auto"})

    def test_emergency_stop_is_immediate(self):
        motor = MotorControllerWorker()
        ser = FakeSerial()
        motor.inject_serial(ser, threading.Lock())
        motor.set_desired(200, 200)
        self.assertTrue(motor.emergency_stop())
        self.assertEqual(ser.packets()[-1], {"left": "+0", "right": "+0", "mode": "auto"})
        self.assertEqual(motor.desired, (0, 0))

    def test_closed_port_does_not_raise(self):
        self.assertFalse(MotorControllerWorker().emergency_stop())


class TestStm32Worker(unittest.TestCase):
    def _worker(self):
        got = []
        return STM32Worker(on_packet=got.append, motor_controller=MotorControllerWorker()), got

    def test_partial_and_malformed_lines(self):
        w, got = self._worker()
        line = json.dumps(stm32_packet()).encode()
        w._buffer = line[:30]
        w._drain_lines()
        self.assertEqual(got, [])
        w._buffer += line[30:] + b"\n{bad json}\n[1,2]\n\n" + line + b"\n"
        w._drain_lines()
        self.assertEqual(len(got), 2)
        self.assertEqual(w.packets_malformed, 2)
        self.assertTrue(w.link_alive)

    def test_buffer_overflow_guard(self):
        w, _ = self._worker()
        w._buffer = b"x" * 9000
        w._drain_lines()
        self.assertEqual(w._buffer, b"")

    def test_reconnect_after_serial_error(self):
        line = json.dumps(stm32_packet()).encode() + b"\n"
        ports = [FakeSerial([line, OSError("unplugged")]), FakeSerial([line])]
        opened = []

        def fake_serial(**_kw):
            s = ports.pop(0)
            opened.append(s)
            return s

        got = []
        motor = MotorControllerWorker()
        disconnects = []
        w = STM32Worker(on_packet=got.append, motor_controller=motor, on_disconnect=lambda: disconnects.append(1))
        with override(STM32_RECONNECT_DELAY_S=0.05), mock.patch.object(stm32_mod.serial, "Serial", fake_serial, create=True):
            w.start()
            deadline = time.time() + 3
            while len(got) < 2 and time.time() < deadline:
                time.sleep(0.02)
            w.stop()
        self.assertEqual(len(got), 2)
        self.assertEqual(len(opened), 2)
        self.assertEqual(disconnects, [1])
        self.assertIsNone(motor._serial)  # revoked on close


if __name__ == "__main__":
    unittest.main()
