"""Reloj y cliente de cache controlados para probar TTL sin esperas reales."""
import math


class MemoryRedis:
    def __init__(self):
        self.now = 0
        self.entries = {}
        self.calls = []
        self.fail = set()

    def call(self, operation, *args):
        self.calls.append((operation, args))
        if operation in self.fail:
            raise TimeoutError("detalle privado del socket")

    def get(self, key):
        self.call("get", key)
        entry = self.entries.get(key)
        if entry is None:
            return None
        value, deadline = entry
        if deadline is not None and deadline <= self.now:
            del self.entries[key]
            return None
        return value

    def set(self, key, value, ex=None):
        self.call("set", key, value, ex)
        self.entries[key] = (value, None if ex is None else self.now + ex)
        return True

    def ttl(self, key):
        self.call("ttl", key)
        entry = self.entries.get(key)
        if entry is None:
            return -2
        if entry[1] is None:
            return -1
        return math.floor(entry[1] - self.now)

    def delete(self, key):
        self.call("delete", key)
        return int(self.entries.pop(key, None) is not None)

    def close(self):
        self.call("close")
