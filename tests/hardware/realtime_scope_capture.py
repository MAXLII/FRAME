"""Physical-board scope diagnostic using FRAME's actual native backend and decoder."""
import argparse
import ctypes as c
import hashlib
import json
import os
import socket
import struct
import time
from pathlib import Path


class Backend:
    def __init__(self, dll):
        self.dll = dll
        self.handle = dll.frame_create()

    def command(self, group, action=None, **fields):
        request = dict(group=group, **fields)
        if action is not None:
            request['action'] = action
        encoded = json.dumps(request).encode()
        operation = c.c_uint64()
        code = self.dll.frame_submit(self.handle, encoded, len(encoded), c.byref(operation))
        if code:
            raise RuntimeError(('submit', code, request))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            size = c.c_uint32()
            code = self.dll.frame_result(self.handle, operation, None, 0, c.byref(size))
            if code == 1:
                time.sleep(0.001)
                continue
            buffer = c.create_string_buffer(size.value)
            code = self.dll.frame_result(self.handle, operation, buffer, size.value, c.byref(size))
            if code:
                raise RuntimeError(('result', code))
            self.dll.frame_release(self.handle, operation)
            response = json.loads(buffer.raw[:size.value])
            if not response.get('ok'):
                raise RuntimeError(response)
            return response['data']
        raise TimeoutError(request)

    def close(self):
        self.dll.frame_destroy(self.handle)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--elf', required=True)
    parser.add_argument('--port', default='COM7')
    parser.add_argument('--control-tcp', action='store_true')
    parser.add_argument('--expected-frequency', type=int)
    parser.add_argument('--host', default='192.168.1.17')
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--output', required=True)
    parser.add_argument('--raw-receiver', action='store_true')
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    dll_path = root / 'build/native/Release/frame_backend.dll'
    os.add_dll_directory(str(dll_path.parent))
    dll = c.CDLL(str(dll_path))
    dll.frame_create.restype = c.c_void_p
    dll.frame_destroy.argtypes = [c.c_void_p]
    dll.frame_submit.argtypes = [c.c_void_p, c.c_char_p, c.c_uint32, c.POINTER(c.c_uint64)]
    dll.frame_result.argtypes = [c.c_void_p, c.c_uint64, c.c_void_p, c.c_uint32, c.POINTER(c.c_uint32)]
    dll.frame_release.argtypes = [c.c_void_p, c.c_uint64]
    common, data = Backend(dll), Backend(dll)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = dict(passed=False, received=0, missing=0, rejected=0, duplicates=0, counter_gaps=0)
    events = (output / 'diagnostic.jsonl').open('w', encoding='utf-8')
    receiver = None

    def record(kind, value):
        events.write(json.dumps(dict(event=kind, monotonic=time.monotonic(), data=value)) + '\n')
        events.flush()

    try:
        if args.control_tcp:
            common.command('connect', transport='tcp', host=args.host, tcp_port=5000, dst=2, wire='e8')
        else:
            common.command('connect', transport='serial', port=args.port, baud=115200, dst=2, wire='e8')
            radio = common.command('serial', 'raw', hex='776966690d0a', duration=0.3)
            report['radio'] = ''.join(bytes.fromhex(row['hex']).decode('utf-8', 'replace') for row in radio['records'] if row['dir'] == 'rx')
        capability = common.command('realtime-scope-control', 'capabilities')
        report['capabilities'] = capability
        frequency = capability['sample_frequency']
        assert frequency > 0, capability
        if args.expected_frequency is not None:
            assert frequency == args.expected_frequency, capability
        assert capability['elf_sha256'].lower() == hashlib.sha256(Path(args.elf).read_bytes()).hexdigest(), capability
        common.command('jlink', 'load', path=str(Path(args.elf).resolve()))
        demo = common.command('jlink', 'expand', name='g_scope_demo', limit=32)
        wave = common.command('jlink', 'expand', name='g_scope_demo.wave', limit=32)
        symbols = {s['name']: s for s in wave + demo}
        try:
            timer = common.command('jlink', 'expand', name='g_bsp_timer_debug', limit=32)
            symbols.update((s['name'], s) for s in timer)
        except RuntimeError:
            pass
        try:
            common.command('jlink', 'expand', name='g_bsp_wifi_debug', limit=4)
            wifi = common.command('jlink', 'expand', name='g_bsp_wifi_debug[1]', limit=16)
            symbols.update((s['name'], s) for s in wifi)
        except RuntimeError:
            pass
        counter_name = 'g_scope_demo.sample_count' if 'g_scope_demo.sample_count' in symbols else 'g_scope_demo.updates'
        names = ['g_scope_demo.wave.' + n for n in ('sine', 'cosine', 'triangle', 'square')]
        names += [counter_name] * 4
        if 'g_bsp_timer_debug.cycle_stamp' in symbols:
            names[5:] = ['g_bsp_timer_debug.' + n for n in ('cycle_stamp', 'max_gap_cycles', 'overdue')]
        if 'g_bsp_wifi_debug[1].max_poll_gap_us' in symbols:
            names[6:] = ['g_bsp_wifi_debug[1].' + n for n in ('max_poll_gap_us', 'max_write_us')]
        if args.profile:
            names[6:] = ['g_bsp_timer_debug.' + n for n in ('busy_cycles', 'max_body_cycles')]
        channels = [dict(channel=i+1, address=symbols[name]['address'], type=9 if i < 3 else 6) for i,name in enumerate(names)]
        report['counter_name'] = counter_name
        common.command('realtime-scope-control', 'configure', channels=channels)
        if args.raw_receiver:
            receiver = socket.create_connection((args.host, 9001), timeout=3)
            receiver.settimeout(0.01)
        else:
            data.command('connect', transport='tcp', protocol='realtime-scope', host=args.host, tcp_port=9001)
        for attempt in range(30):
            if common.command('realtime-scope-control', 'status')['data_connected']:
                break
            time.sleep(0.05)
        if not args.raw_receiver:
            data.command('realtime-scope', 'configure', channels=channels)
            data.command('realtime-scope', 'start', frequency=frequency)
        common.command('realtime-scope-control', 'start')
        started = time.monotonic()
        next_status = started
        previous = None
        previous_cycle = None
        previous_busy = None
        busy_total = 0
        cycle_total = cycle_intervals = max_cycle_gap = 0
        counter_values = []
        crossings = []; previous_signal = None
        wire = bytearray(); wire_index = None; logical = 0; missing = 0
        while time.monotonic() - started < args.seconds:
            if receiver:
                try: wire.extend(receiver.recv(65536))
                except socket.timeout: pass
                rows = []
                consumed = 0
                while len(wire) - consumed >= 37:
                    frame = wire[consumed:consumed+37]; consumed += 37
                    assert frame[0] == 0xea and int.from_bytes(frame[-3:-1],'little') == 32 and sum(frame[:-1]) & 255 == frame[-1], frame.hex()
                    delta = 1 if wire_index is None else (frame[1] - wire_index) & 255
                    missing += max(0,delta-1); logical += delta; wire_index = frame[1]
                    rows.append(dict(index=logical-1,values=struct.unpack('<fffIIIII',frame[2:34])))
                del wire[:consumed]
                batch = dict(rows=rows,missing=missing,duplicates=0,rejected=0,pending=0)
            else:
                batch = data.command('realtime-scope', 'drain')
            rows = batch['rows']
            if rows and names[6].endswith('max_poll_gap_us'):
                report['max_transport_poll_gap_us'] = rows[-1]['values'][6]
                report['max_socket_write_us'] = rows[-1]['values'][7]
            if rows and args.profile:
                report['max_isr_us'] = rows[-1]['values'][7] / 240
            report['received'] += len(rows)
            for key in ('missing','duplicates','rejected'):
                report[key] = batch[key]
            for row in rows:
                signal = row['values'][0]
                if previous_signal is not None and previous_signal < 0 <= signal:
                    crossings.append(row['index'])
                previous_signal = signal
                value = row['values'][4]
                if counter_name.endswith('sample_count') and previous is not None and value != (int(previous) + 1) & 0xffffffff:
                    report['counter_gaps'] += 1
                if previous is None or value != previous:
                    counter_values.append((row['index'], value))
                previous = value
                if names[5].endswith('cycle_stamp'):
                    stamp = int(row['values'][5])
                    if previous_cycle is not None:
                        delta = (stamp - previous_cycle) & 0xffffffff
                        cycle_total += delta
                        cycle_intervals += 1
                        max_cycle_gap = max(max_cycle_gap, delta)
                    previous_cycle = stamp
                    if args.profile:
                        busy = int(row['values'][6])
                        if previous_busy is not None:
                            busy_total += (busy - previous_busy) & 0xffffffff
                        previous_busy = busy
            if batch.get('fault'):
                report['fault'] = batch['fault']
                break
            now = time.monotonic()
            if now >= next_status:
                status = common.command('realtime-scope-control', 'status')
                report['device'] = status
                record('status', dict(status, received=report['received'], missing=batch['missing'], rejected=batch['rejected'], pending=batch['pending']))
                if not status['running']:
                    break
                next_status = now + 0.5
        report['elapsed_s'] = time.monotonic() - started
        report['receive_hz'] = report['received'] / report['elapsed_s']
        if cycle_total:
            report['hardware_hz'] = cycle_intervals * 240000000 / cycle_total
            report['hardware_max_interval_us'] = max_cycle_gap / 240
            if args.profile:
                report['isr_cpu_percent'] = busy_total * 100 / cycle_total
        report['counter_transitions'] = counter_values[:50]
        if len(crossings) >= 2:
            report['waveform_hz'] = frequency * (len(crossings)-1) / (crossings[-1]-crossings[0])
            report['wave_period_samples_min'] = min(b-a for a,b in zip(crossings,crossings[1:]))
            report['wave_period_samples_max'] = max(b-a for a,b in zip(crossings,crossings[1:]))
        report['passed'] = (report.get('device', {}).get('running', False) and not report.get('fault')
            and all(report[k] == 0 for k in ('missing','duplicates','rejected','counter_gaps'))
            and report['device']['overflows'] == 0 and report['elapsed_s'] >= args.seconds)
    finally:
        try:
            common.command('realtime-scope-control', 'stop')
        except Exception:
            pass
        common.close()
        data.close()
        if receiver:
            receiver.close()
        events.close()
        (output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'counter_transitions'}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
