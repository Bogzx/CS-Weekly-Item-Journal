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
        client.post('/logout', data={})
        resp = client.post('/login', data={'username': name, 'password': 'wrong'})

        assert resp.status_code == 200  # counting starts again from zero


class TestLogout:
    def test_logout_is_post_only(self, logged_in):
        assert logged_in.get('/logout').status_code == 405
        with logged_in.session_transaction() as sess:
            assert 'user_id' in sess

    def test_logout_needs_the_csrf_token(self, logged_in):
        assert logged_in.post('/logout', data={}, csrf=False).status_code == 400
        with logged_in.session_transaction() as sess:
            assert 'user_id' in sess

    def test_logout_with_token(self, logged_in):
        assert logged_in.post('/logout', data={}).status_code == 302
        with logged_in.session_transaction() as sess:
            assert 'user_id' not in sess

    def test_pages_offer_a_logout_form_not_a_link(self, logged_in):
        html = logged_in.get('/').get_data(as_text=True)

        assert 'class="logout-form"' in html
        assert 'href="/logout"' not in html


class TestTrustedProxies:
    def fail_logins(self, client, name, ip, times):
        for _ in range(times):
            client.post('/login', data={'username': name, 'password': 'wrong'},
                        headers={'X-Forwarded-For': ip})

    def test_forwarded_for_is_ignored_by_default(self, appmod, client):
        """Without a trusted proxy, rotating X-Forwarded-For must not dodge the throttle."""
        name = f'user_{uuid.uuid4().hex[:8]}'
        register(client, name)
        for i in range(appmod.login_throttle.max_failures):
            self.fail_logins(client, name, f'10.0.0.{i}', 1)

        resp = client.post('/login', data={'username': name, 'password': 'wrong'},
                           headers={'X-Forwarded-For': '10.0.0.99'})

        assert resp.status_code == 429

    def test_trusted_proxy_throttles_the_real_client(self, appmod, client):
        name = f'user_{uuid.uuid4().hex[:8]}'
        register(client, name)
        appmod.trust_proxies(1)
        try:
            self.fail_logins(client, name, '203.0.113.7', appmod.login_throttle.max_failures)
            locked = client.post('/login', data={'username': name, 'password': 'wrong'},
                                 headers={'X-Forwarded-For': '203.0.113.7'})
            other = client.post('/login', data={'username': name, 'password': 'wrong'},
                                headers={'X-Forwarded-For': '198.51.100.2'})
        finally:
            appmod.trust_proxies(0)

        assert locked.status_code == 429
        assert other.status_code == 200


class TestThrottleBypasses:
    def test_begin_attempt_counts_before_the_password_check(self, appmod):
        throttle, _ = make(appmod)
        assert [throttle.begin_attempt('ip', 'victim') for _ in range(4)] == [0, 0, 0, 60]
        # A refused attempt is not recorded, so the lock does not extend itself.
        assert len(throttle._failures['ip']) == 3

    def test_success_clears_only_that_username(self, appmod):
        throttle, _ = make(appmod)
        throttle.begin_attempt('ip', 'victim')
        throttle.begin_attempt('ip', 'victim')
        throttle.begin_attempt('ip', 'attacker')

        throttle.succeeded('ip', 'attacker')

        assert [u for _, u in throttle._failures['ip']] == ['victim', 'victim']
        throttle.begin_attempt('ip', 'victim')
        assert throttle.retry_after('ip') == 60

    def test_own_account_login_does_not_reset_guesses_at_another(self, appmod, client):
        """Guess max-1 times, log in as yourself, repeat: used to be unlimited."""
        victim, attacker = (f'user_{uuid.uuid4().hex[:8]}' for _ in range(2))
        register(client, victim)
        register(client, attacker)
        codes = []
        for _ in range(3):
            for _ in range(appmod.login_throttle.max_failures - 1):
                codes.append(client.post('/login', data={'username': victim, 'password': 'guess'}).status_code)
            client.post('/login', data={'username': attacker, 'password': 'pw-123456'})
            client.post('/logout', data={})

        assert codes.count(200) == appmod.login_throttle.max_failures
        assert 429 in codes

    def test_parallel_guesses_cannot_outrun_the_count(self, appmod, client, monkeypatch):
        """Every request used to pass the lock check while the slow password
        hash of the others was still running, so a burst of N guesses got N
        tries instead of max_failures."""
        import threading
        import time

        name = f'user_{uuid.uuid4().hex[:8]}'
        register(client, name)

        def slow_check(pw_hash, password):
            time.sleep(0.2)
            return False

        monkeypatch.setattr(appmod, 'check_password_hash', slow_check)
        codes = []

        def guess():
            with appmod.app.test_client() as c:
                codes.append(c.post('/login', data={'username': name, 'password': 'x'}).status_code)

        threads = [threading.Thread(target=guess) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert codes.count(200) == appmod.login_throttle.max_failures
        assert codes.count(429) == 12 - appmod.login_throttle.max_failures


class TestThrottleKey:
    def test_ipv4_is_its_own_key(self, appmod):
        assert appmod.throttle_key('203.0.113.7') == '203.0.113.7'

    def test_ipv6_is_grouped_by_64(self, appmod):
        assert (appmod.throttle_key('2001:db8:1:2::1')
                == appmod.throttle_key('2001:db8:1:2:ffff:ffff:ffff:ffff')
                == '2001:db8:1:2::/64')
        assert appmod.throttle_key('2001:db8:1:3::1') != appmod.throttle_key('2001:db8:1:2::1')

    def test_ipv4_mapped_ipv6_is_the_ipv4_address(self, appmod):
        assert appmod.throttle_key('::ffff:203.0.113.7') == '203.0.113.7'

    def test_missing_or_odd_address(self, appmod):
        assert appmod.throttle_key(None) == 'unknown'
        assert appmod.throttle_key('not-an-ip') == 'not-an-ip'

    def test_rotating_ipv6_addresses_in_one_64_share_a_lock(self, appmod, client):
        name = f'user_{uuid.uuid4().hex[:8]}'
        register(client, name)
        codes = [client.post('/login', data={'username': name, 'password': 'wrong'},
                             environ_base={'REMOTE_ADDR': f'2001:db8::{i + 1:x}'}).status_code
                 for i in range(appmod.login_throttle.max_failures + 1)]

        assert codes[-1] == 429
