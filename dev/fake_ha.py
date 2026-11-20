"""A stand-in for Home Assistant that answers from readings in memory, like its history API would."""
import bisect


class FakeHA:
    def __init__(self, readings: dict, states: dict = None):
        self.readings = {k: sorted(v) for k, v in readings.items()}
        self.states = states or {}
        self.set_states: dict = {}
        self.events: list = []
        self.services: list = []
        self.history_calls = 0

    async def history(self, entity_id, start, end):
        """The state at `start` first (as Home Assistant does), then every change up to `end`."""
        self.history_calls += 1
        rows = self.readings.get(entity_id, [])
        times = [t for t, _ in rows]
        i = bisect.bisect_right(times, start)
        out = [(start, rows[i - 1][1])] if i else []
        j = bisect.bisect_right(times, end)
        return out + [r for r in rows[i:j]]

    async def state_at(self, entity_id, ts):
        value = self.states.get(entity_id)
        return value(ts) if callable(value) else value

    async def set_state(self, entity_id, state, attributes):
        self.set_states[entity_id] = (state, attributes)

    async def fire_event(self, event_type, data):
        self.events.append((event_type, data))

    async def call_service(self, service, data):
        self.services.append((service, data))

    async def close(self):
        pass
