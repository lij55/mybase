"""Offline regression checks for the acceptance runner's failure-sensitive helpers."""
import http.client
import json
from pathlib import Path
import socket
import struct
import sys
import time
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from integration_support import Instance, WebSocket


class AcceptanceHelpersTests(unittest.TestCase):
    def test_http_failure_does_not_print_signed_url(self):
        instance = Instance.__new__(Instance)
        instance.values = {'SUPABASE_PUBLISHABLE_KEY': 'key'}
        instance.base = 'http://127.0.0.1'
        instance.opener = Mock()
        instance.opener.open.side_effect = http.client.InvalidURL('path?token=secret')
        with self.assertRaises(AssertionError) as failure:
            instance.api('GET', '/path?token=secret')
        self.assertNotIn('secret', str(failure.exception))
        self.assertTrue(failure.exception.__suppress_context__)

    def test_websocket_fragmented_json_with_ping_and_partial_reads(self):
        client = WebSocket.__new__(WebSocket)
        client.sock = Mock()
        client.buffer = b''
        payload = json.dumps({'event': 'broadcast'}).encode()
        frames = (bytes([1, 5]) + payload[:5] + b'\x89\x01p'
                  + bytes([128, len(payload) - 5]) + payload[5:])
        client.sock.recv.side_effect = [frames[i:i + 3] for i in range(0, len(frames), 3)]
        self.assertEqual(client.receive(time.monotonic() + 1), {'event': 'broadcast'})
        pong = client.sock.sendall.call_args.args[0]
        self.assertEqual(pong[:2], b'\x8a\x81')
        self.assertEqual(pong[6] ^ pong[2], ord('p'))

    def test_websocket_extended_length_and_masked_client_frames(self):
        client = WebSocket.__new__(WebSocket)
        client.sock = Mock()
        payload = json.dumps({'value': 'x' * 200}).encode()
        client.buffer = b'\x81\x7e' + struct.pack('!H', len(payload)) + payload
        self.assertEqual(client.receive(time.monotonic() + 1)['value'], 'x' * 200)
        client.send_frame(payload)
        frame = client.sock.sendall.call_args.args[0]
        self.assertEqual(frame[:2], b'\x81\xfe')
        self.assertEqual(int.from_bytes(frame[2:4], 'big'), len(payload))
        self.assertEqual(bytes(c ^ frame[4 + i % 4] for i, c in enumerate(frame[8:])), payload)

    def test_websocket_close_and_timeout_fail(self):
        client = WebSocket.__new__(WebSocket)
        client.sock = Mock()
        client.buffer = b'\x88\x00'
        with self.assertRaisesRegex(AssertionError, 'close'):
            client.until(lambda m: True)
        client.sock.recv.side_effect = socket.timeout()
        with self.assertRaises(TimeoutError):
            client.until(lambda m: True)


if __name__ == '__main__':
    unittest.main()
