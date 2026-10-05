"""Regression tests for USB removal while the vendor keeps a cached snapshot."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import EEG


class UsbReconnectTests(unittest.TestCase):
    def test_cached_online_cannot_hide_missing_linux_port(self):
        snapshot = SimpleNamespace(online=True, seq=1, attention=80)
        with patch("EEG.os.path.exists", return_value=False):
            with self.assertRaises(ConnectionError):
                EEG._check_headband_connection("/dev/serial/by-id/headband", snapshot)

    def test_device_disconnect_overrides_cached_snapshot_online(self):
        snapshot = SimpleNamespace(online=True, seq=1)
        device = SimpleNamespace(online={"adapter": False, "headband_ble": True})
        with self.assertRaises(ConnectionError):
            EEG._check_headband_connection("COM1", snapshot, device)

    def test_worker_publishes_disconnect_and_reopens_with_new_generation(self):
        stop = threading.Event()
        frames = []
        cached = SimpleNamespace(seq=1, attention=80, state="normal", wear=True, online=True)
        device = SimpleNamespace(snapshot=lambda: cached)
        context = MagicMock()
        context.__enter__.return_value = device

        def capture(lane, **frame):
            frames.append(frame)
            if frame.get("generation") == 2:
                stop.set()

        # Open, first sample; unplug before the next poll; plug back in.
        presence = [True, True, True, False, True, True, True]
        with patch("EEG._stop", stop), patch.object(stop, "wait", return_value=False), \
                patch("EEG._headband_ports", return_value=("/dev/ttyACM0",)), \
                patch("EEG.os.path.exists", side_effect=presence), \
                patch("EEG.HeadbandUsb", return_value=context) as opener, \
                patch("EEG._publish"), patch("EEG._emit_frame", side_effect=capture):
            EEG._headband_worker(1)
        self.assertEqual(opener.call_count, 2)
        self.assertEqual(context.__exit__.call_count, 2)
        self.assertEqual([f.get("connected") for f in frames], [True, False, True])
        self.assertEqual(frames[1]["state"], "off")
        self.assertIsNone(frames[1]["worn"])
        self.assertEqual(frames[1]["reason"], "connection_error")
        self.assertEqual([f["generation"] for f in frames if "generation" in f], [1, 2])
        # A restarted vendor sequence is fresh only in the new connection.
        self.assertEqual([f["sequence"] for f in frames if "sequence" in f], [1, 1])

    def test_initial_offline_handshake_does_not_reopen_adapter(self):
        stop = threading.Event()
        snapshots = [SimpleNamespace(online=False),
                     SimpleNamespace(online=True, seq=1, attention=80, state="normal", wear=True)]
        device = MagicMock(spec=["snapshot"])
        device.snapshot.side_effect = snapshots
        context = MagicMock()
        context.__enter__.return_value = device
        frames = []

        def capture(lane, **frame):
            frames.append(frame)
            if frame.get("sequence"):
                stop.set()

        with patch("EEG._stop", stop), patch.object(stop, "wait", return_value=False), \
                patch("EEG._headband_ports", return_value=("COM1",)), \
                patch("EEG.HeadbandUsb", return_value=context) as opener, \
                patch("EEG._publish"), patch("EEG._emit_frame", side_effect=capture):
            EEG._headband_worker(1)
        self.assertEqual(opener.call_count, 1)
        self.assertEqual([f["connected"] for f in frames], [False, True])


if __name__ == "__main__":
    unittest.main()
