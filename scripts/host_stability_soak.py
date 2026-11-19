"""Bounded, isolated Host HTTP soak; no real PostgreSQL or profile is opened.

Run from the repository root: python -m scripts.host_stability_soak --seconds 60
"""
import argparse
import concurrent.futures
import ctypes
import json
import logging
import os
import socket
import struct
import threading
import tempfile
import time
import urllib.error
import urllib.request
from unittest.mock import patch
from logging.handlers import RotatingFileHandler

from core.network.server import DatabaseServer
from tests.test_server_stability import Pool


def tcp_sockets_for_process():
    """Windows TCP IPv4 connections (including LISTEN), owned by this PID."""
    if os.name != 'nt':
        return None
    from ctypes import wintypes
    get_table = ctypes.windll.iphlpapi.GetExtendedTcpTable
    get_table.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                          wintypes.BOOL, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG]
    get_table.restype = wintypes.DWORD
    size = wintypes.DWORD()
    if get_table(None, ctypes.byref(size), False, socket.AF_INET, 5, 0) != 122:
        return None
    data = ctypes.create_string_buffer(size.value)
    if get_table(data, ctypes.byref(size), False, socket.AF_INET, 5, 0) != 0:
        return None
    count = struct.unpack_from('<I', data, 0)[0]
    return sum(struct.unpack_from('<I', data, 4 + index * 24 + 20)[0] == os.getpid()
               for index in range(count))


def resident_memory_mb():
    """Query the actual working set; 0.0 from app diagnostics is not a sample."""
    if os.name != 'nt':
        return None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('faults', wintypes.DWORD),
                    ('peak', ctypes.c_size_t), ('working_set', ctypes.c_size_t),
                    ('peak_paged', ctypes.c_size_t), ('paged', ctypes.c_size_t),
                    ('peak_nonpaged', ctypes.c_size_t), ('nonpaged', ctypes.c_size_t),
                    ('pagefile', ctypes.c_size_t), ('peak_pagefile', ctypes.c_size_t)]
    get_handle = ctypes.windll.kernel32.GetCurrentProcess
    get_handle.restype = ctypes.c_void_p  # HANDLE is pointer-sized on 64-bit Windows.
    get_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    counters = Counters()
    counters.size = ctypes.sizeof(Counters)
    if not get_info(get_handle(), ctypes.byref(counters), counters.size):
        return None
    return round(counters.working_set / (1024 * 1024), 2)


def request(url, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=3) as reply:
        return reply.status, reply.read()


def summarize(values):
    if not values:
        return None
    ordered = sorted(values)
    return {name: round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))], 2)
            for name, fraction in (('p50_ms', .50), ('p95_ms', .95), ('p99_ms', .99), ('max_ms', 1))}


def run(seconds):
    if seconds <= 0:
        raise ValueError('Soak duration must be positive')
    profile = type('TestProfile', (), {'database_name': 'isolated_soak', 'get_value': lambda self, key: ''})()
    manager = type('TestManager', (), {'selected_profile': profile})()
    database = type('FakeHostDB', (), {'profile_manager': manager, 'registered_classes': {}})()
    server = DatabaseServer(database, port=0, max_request_threads=16, request_timeout=1,
                            max_request_bytes=2 * 1024 * 1024)
    pool = Pool()
    user = {'id': 1, 'username': 'soak-test', 'role_id': 1,
            'is_superadmin': True, 'permissions': {}}
    failures = {}
    latencies = []
    samples = []
    bursts = 0
    attempts = 0
    logins = 0
    disconnects = 0
    recoveries = 0
    monitor_stop = threading.Event()
    # Capture the same per-request INFO diagnostics and rotation under load,
    # but never write to the app's normal logs or keep an isolated test log.
    log_directory = tempfile.TemporaryDirectory(prefix='inventory-host-soak-')
    handler = RotatingFileHandler(os.path.join(log_directory.name, 'app.log'),
                                  maxBytes=5 * 1024 * 1024, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'))
    server_logger = logging.getLogger('core.network.server')
    server_logger.addHandler(handler)

    def fetch(_db, _section, **_kwargs):
        time.sleep(.003)
        return [{'ID': 1, 'name': 'isolated-test'}]

    def login(base):
        nonlocal logins
        status, response = request(base + '/login', b'{"username":"soak-test","password":"test-only"}')
        if status != 200:
            raise RuntimeError('Isolated authentication failed')
        logins += 1
        return json.loads(response)['token']

    def client_burst(base, token):
        local_latencies = []
        local_failures = {}
        for _ in range(8):
            started = time.perf_counter()
            try:
                status, data = request(
                    base + '/rpc', b'{"method":"get_items","args":["Products"]}', token
                )
                if status != 200 or json.loads(data).get('result') != [{'ID': 1, 'name': 'isolated-test'}]:
                    local_failures['incorrect_response'] = local_failures.get('incorrect_response', 0) + 1
            except Exception as error:
                key = type(error).__name__
                local_failures[key] = local_failures.get(key, 0) + 1
            local_latencies.append((time.perf_counter() - started) * 1000)
        return local_latencies, local_failures

    def monitor():
        while not monitor_stop.is_set():
            samples.append({
                'rss_mb': resident_memory_mb(),
                'threads': threading.active_count(),
                'tcp_sockets': tcp_sockets_for_process(),
                'pool_in_use': server._checked_out,
                'http_active': server._httpd.active_requests if server._httpd else 0,
            })
            monitor_stop.wait(.25)

    started = time.monotonic()
    cpu_started = time.process_time()
    with patch('core.network.server.load_server_config', return_value={}), patch(
        'core.network.server.ThreadedConnectionPool', return_value=pool
    ), patch('core.network.server.UserManager.verify_login', return_value=user), patch(
        'core.database.Database.get_sale_catalog', return_value={}
    ), patch('core.database.Database.get_items', fetch):
        server.start()
        base = f'http://127.0.0.1:{server.port}'
        monitor_thread = threading.Thread(target=monitor, name='IsolatedSoakMonitor', daemon=True)
        monitor_thread.start()
        try:
            tokens = [login(base) for _ in range(6)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                while time.monotonic() - started < seconds:
                    if bursts and bursts % 5 == 0:
                        tokens = [login(base) for _ in tokens]
                    results = list(executor.map(lambda token: client_burst(base, token), tokens))
                    attempts += 8 * len(tokens)
                    bursts += 1
                    for times, errors in results:
                        latencies.extend(times)
                        for name, count in errors.items():
                            failures[name] = failures.get(name, 0) + count
                    if bursts % 5 == 0:
                        interrupted = socket.create_connection(('127.0.0.1', server.port), timeout=2)
                        interrupted.sendall(b'POST /login HTTP/1.1\r\nHost: localhost\r\nContent-Length: 99\r\n\r\n{')
                        interrupted.close()
                        disconnects += 1
                    time.sleep(.15)
                    httpd = server._httpd
                    if (server._checked_out == 0 and not pool.outstanding and httpd
                            and httpd.active_requests == 0):
                        recoveries += 1
                    time.sleep(.4)
            status, data = request(base + '/health', token=tokens[0])
            if status != 200 or not all(json.loads(data).values()):
                failures['final_health'] = 1
        finally:
            monitor_stop.set()
            monitor_thread.join(3)
            server.stop()
            server_logger.removeHandler(handler)
            handler.close()
            log_directory.cleanup()
    elapsed = time.monotonic() - started
    cpu_elapsed = time.process_time() - cpu_started
    end = {'rss_mb': resident_memory_mb(),
           'threads': threading.active_count(), 'tcp_sockets': tcp_sockets_for_process(),
           'pool_in_use': server._checked_out, 'pool_outstanding': len(pool.outstanding),
           'pool_closed': pool.closed}
    first = samples[0] if samples else {}
    result = {
        'duration_seconds': round(elapsed, 2), 'requested_seconds': seconds,
        'rpc_attempts': attempts, 'failed_rpc': sum(failures.values()), 'failure_categories': failures,
        'bursts': bursts, 'bursts_recovered': recoveries, 'client_disconnects': disconnects,
        'logins': logins, 'sessions_retained': len(server.sessions._sessions),
        'rpc_latency': summarize(latencies),
        'cpu_seconds': round(cpu_elapsed, 2),
        'cpu_one_core_percent': round(cpu_elapsed / elapsed * 100, 2),
        'rss_mb': {'initial': first.get('rss_mb'),
                   'peak': max((s['rss_mb'] for s in samples if s['rss_mb'] is not None), default=None),
                   'after_stop': end['rss_mb']},
        'threads': {'initial': first.get('threads'),
                    'peak': max((s['threads'] for s in samples), default=None),
                    'after_stop': end['threads']},
        'tcp_sockets': {'initial': first.get('tcp_sockets'),
                        'peak': max((s['tcp_sockets'] for s in samples if s['tcp_sockets'] is not None), default=None),
                        'after_stop': end['tcp_sockets']},
        'pool': {'peak_checked_out': max((s['pool_in_use'] for s in samples), default=0),
                 'peak_realized': pool.high_water, 'after_stop_checked_out': end['pool_in_use'],
                 'after_stop_outstanding': end['pool_outstanding'], 'closed': end['pool_closed']},
        'http_peak_active': max((s['http_active'] for s in samples), default=0),
    }
    print(json.dumps(result, indent=2))
    if failures or pool.outstanding or not pool.closed or recoveries != bursts:
        raise SystemExit(1)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=60)
    options = parser.parse_args()
    run(options.seconds)
