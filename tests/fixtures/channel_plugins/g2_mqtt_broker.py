"""Small local MQTT wire service; the production worker imports real paho."""

import socketserver
import struct
import threading


def packet(header, data=b""):
    length, encoded = len(data), bytearray()
    while True:
        digit = length % 128
        length //= 128
        encoded.append(digit | (128 if length else 0))
        if not length:
            return bytes([header]) + encoded + data


def read_exact(stream, length):
    result = bytearray()
    while len(result) < length:
        chunk = stream.recv(length - len(result))
        if not chunk:
            raise EOFError
        result.extend(chunk)
    return bytes(result)


def mqtt_string(value):
    raw = value.encode()
    return struct.pack("!H", len(raw)) + raw


def take_string(data, offset):
    size = struct.unpack("!H", data[offset : offset + 2])[0]
    offset += 2
    return data[offset : offset + size].decode(), offset + size


class WebSocketStream:
    def __init__(self, connection):
        self.connection, self.buffer = connection, b""

    def recv(self, length):
        from websockets.exceptions import ConnectionClosed

        if not self.buffer:
            try:
                self.buffer = self.connection.recv()
            except ConnectionClosed as exc:
                raise EOFError from exc
        result, self.buffer = self.buffer[:length], self.buffer[length:]
        return result

    def sendall(self, data):
        self.connection.send(data)

    def shutdown(self, _how):
        self.connection.close()

    def close(self):
        self.connection.close()


class Broker:
    def __init__(self, *, tls_context=None, websocket=False):
        self.clients, self.publishes, self.subscriptions = [], [], []
        self.subscription_packets = []
        self.connect_packets, self.peer_certificates = [], []
        self.handshake_errors = []
        self.confirm = True
        self.connect_code = 0
        self.connect_code_provider = None
        self.connections = 0
        self.lock = threading.Lock()
        broker = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                broker.handle(self.request)

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

            def get_request(self):
                stream, address = super().get_request()
                if tls_context:
                    try:
                        stream = tls_context.wrap_socket(
                            stream, server_side=True
                        )
                    except OSError as exc:
                        broker.handshake_errors.append(str(exc))
                        stream.close()
                        raise
                    broker.peer_certificates.append(stream.getpeercert())
                return stream, address

        if websocket:
            from websockets.sync.server import serve

            self.server = serve(
                lambda connection: self.handle(WebSocketStream(connection)),
                "127.0.0.1",
                0,
                ssl=tls_context,
                subprotocols=["mqtt"],
            )
            self.port = self.server.socket.getsockname()[1]
        else:
            self.server = Server(("127.0.0.1", 0), Handler)
            self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()

    def handle(self, stream):
        with self.lock:
            self.clients.append(stream)
            self.connections += 1
        try:
            while True:
                header = read_exact(stream, 1)[0]
                remaining, multiplier = 0, 1
                while True:
                    digit = read_exact(stream, 1)[0]
                    remaining += (digit & 127) * multiplier
                    if digit < 128:
                        break
                    multiplier *= 128
                body = read_exact(stream, remaining)
                kind = header >> 4
                if kind == 1:
                    _, offset = take_string(body, 0)
                    flags = body[offset + 1]
                    keepalive = struct.unpack(
                        "!H", body[offset + 2 : offset + 4]
                    )[0]
                    client_id, offset = take_string(body, offset + 4)
                    username = password = ""
                    if flags & 128:
                        username, offset = take_string(body, offset)
                    if flags & 64:
                        password, offset = take_string(body, offset)
                    self.connect_packets.append(
                        {
                            "client_id": client_id,
                            "username": username,
                            "password": password,
                            "keepalive": keepalive,
                            "clean_session": bool(flags & 2),
                        }
                    )
                    code = (
                        self.connect_code_provider()
                        if self.connect_code_provider
                        else self.connect_code
                    )
                    stream.sendall(packet(0x20, bytes([0, code])))
                elif kind == 8:
                    topic, offset = take_string(body, 2)
                    self.subscriptions.append(topic)
                    self.subscription_packets.append(
                        {"topic": topic, "qos": body[offset]}
                    )
                    stream.sendall(packet(0x90, body[:2] + b"\x02"))
                elif kind == 3:
                    topic, offset = take_string(body, 0)
                    qos, mid = (header >> 1) & 3, b""
                    if qos:
                        mid, offset = body[offset : offset + 2], offset + 2
                    self.publishes.append((topic, body[offset:].decode(), qos))
                    if qos and self.confirm:
                        stream.sendall(packet(0x40 if qos == 1 else 0x50, mid))
                elif kind == 6 and self.confirm:
                    stream.sendall(packet(0x70, body[:2]))
                elif kind == 12:
                    stream.sendall(packet(0xD0))
                elif kind == 14:
                    return
        except (EOFError, OSError):
            pass
        finally:
            with self.lock:
                self.clients.remove(stream)

    def emit(self, topic, text, *, mid=1):
        # Reusing MID is intentional: it is not a business event identity.
        payload = text if isinstance(text, bytes) else text.encode()
        data = mqtt_string(topic) + struct.pack("!H", mid) + payload
        with self.lock:
            clients = tuple(self.clients)
        assert len(clients) == 1
        clients[0].sendall(packet(0x32, data))

    def disconnect(self):
        with self.lock:
            clients = tuple(self.clients)
        for client in clients:
            try:
                client.shutdown(2)
            except OSError:
                pass  # Peer may already have completed its MQTT disconnect.
            client.close()

    def close(self):
        self.disconnect()
        self.server.shutdown()
        if hasattr(self.server, "server_close"):
            self.server.server_close()
        self.thread.join()
