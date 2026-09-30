"""Failed-login throttling (M6: .env.EXAMPLE used to advertise a login rate
limit that no code implemented)."""

import uuid

from conftest import register


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(appmod, max_failures=3, window=60):
    clock = FakeClock()
    return appmod.LoginThrottle(max_failures, window, clock=clock), clock


class TestLoginThrottle:
    def test_locks_after_max_failures(self, appmod):
        throttle, _ = make(appmod)
        for _ in range(2):
            throttle.record_failure('ip')
        assert throttle.retry_after('ip') == 0

        throttle.record_failure('ip')

        assert throttle.retry_after('ip') == 60

    def test_lock_expires_with_the_window(self, appmod):
        throttle, clock = make(appmod)
        for _ in range(3):
            throttle.record_failure('ip')

        clock.now += 45
        assert throttle.retry_after('ip') == 15
        clock.now += 15
        assert throttle.retry_after('ip') == 0

    def test_old_failures_do_not_accumulate(self, appmod):
        throttle, clock = make(appmod)
        throttle.record_failure('ip')
        throttle.record_failure('ip')
        clock.now += 61
        throttle.record_failure('ip')

        assert throttle.retry_after('ip') == 0

    def test_clients_are_independent_and_reset_clears(self, appmod):
        throttle, _ = make(appmod)
        for _ in range(3):
            throttle.record_failure('a')

        assert throttle.retry_after('b') == 0
        throttle.reset('a')
        assert throttle.retry_after('a') == 0

    def test_zero_disables(self, appmod):
        throttle, _ = make(appmod, max_failures=0)
        for _ in range(10):
            throttle.record_failure('ip')

        assert throttle.retry_after('ip') == 0

    def test_memory_is_bounded_per_client(self, appmod):
        throttle, _ = make(appmod)
        for _ in range(100):
            throttle.record_failure('ip')

        assert len(throttle._failures['ip']) == 3


class TestLoginRoute:
    def test_locked_out_after_repeated_failures_even_with_the_right_password(self, appmod, client):
        name = f'user_{uuid.uuid4().hex[:8]}'
        register(client, name)
        for _ in range(appmod.login_throttle.max_failures):
            resp = client.post('/login', data={'username': name, 'password': 'wrong'})
            assert resp.status_code == 200

        resp = client.post('/login', data={'username': name, 'password': 'pw-123456'})

        assert resp.status_code == 429
        assert b'Too many failed login attempts' in resp.data
        with client.session_transaction() as sess:
            assert 'user_id' not in sess

    def test_success_clears_earlier_failures(self, appmod, client):
        name = f'user_{uuid.uuid4().hex[:8]}'
        register(client, name)
        for _ in range(appmod.login_throttle.max_failures - 1):
            client.post('/login', data={'username': name, 'password': 'wrong'})

        assert client.post('/login', data={'username': name, 'password': 'pw-123456'}).status_code == 302
        client.get('/logout')
        resp = client.post('/login', data={'username': name, 'password': 'wrong'})

        assert resp.status_code == 200  # counting starts again from zero
