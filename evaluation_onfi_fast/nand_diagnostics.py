"""Read and validate passive NAND timing observations; all durations are ns."""
from pathlib import Path

STAGES = ('lun_ns', 'input_ns', 'onfi_ns', 'array_ns', 'channel_late_ns',
          'channel_queue_ns', 'channel_service_ns', 'pcie_tail_ns')


def records(path, kind):
    return [{k: int(v) for k, v in (s.split('=', 1) for s in line.split()[1:])}
            for line in Path(path).read_text().splitlines() if line.startswith(kind + ' ')]


def validate(folder, enabled, onfi):
    after = folder / 'measure.after.stats'
    config, = records(after, 'nand_diag')
    if config['enabled'] != enabled or config['active']:
        raise ValueError('diagnostic allocation/gate state mismatch')
    if not enabled:
        return
    before = folder / 'measure.before.stats'
    stats = records(after, 'nand_breakdown')
    hist = records(after, 'nand_hist')
    assert len(stats) == 16 and len(hist) == 320
    assert sum(s['ops'] for s in records(before, 'nand_breakdown')) == 0
    old_onfi = sum(s['wait_events'] for s in records(before, 'onfi'))
    old_ns = sum(s['wait_ns'] for s in records(before, 'onfi'))
    assert sum(s['onfi_events'] for s in stats) == sum(s['wait_events'] for s in records(after, 'onfi')) - old_onfi
    assert sum(s['onfi_ns'] for s in stats) == sum(s['wait_ns'] for s in records(after, 'onfi')) - old_ns
    for op, key in [(0, 'reads'), (1, 'programs')]:
        count = sum(s[key] for s in records(after, 'die')) - sum(s[key] for s in records(before, 'die'))
        assert sum(s['ops'] for s in stats if s['op'] == op) == count, 'NAND observer window mismatch'
    for s in stats:
        assert not s['invalid'] and sum(s[k] for k in STAGES) == s['total_ns']
        assert s['after_read_ns'] + s['after_program_ns'] + s['after_other_ns'] == s['lun_ns']
        assert s['cross_events'] + s['same_events'] == s['onfi_events']
        if 'blocker_queued_ns' in s:
            assert sum(s[k] for k in ('blocker_queued_ns', 'blocker_sense_ns', 'blocker_output_ns')) == s['onfi_ns']
        h = [r for r in hist if all(r[k] == s[k] for k in ('channel', 'lun', 'op'))]
        assert sum(r['total'] for r in h) == s['ops']
        assert sum(r['same_lun'] for r in h) == s['lun_events']
        assert sum(r['onfi'] for r in h) == s['onfi_events']
        if not onfi or s['op'] == 0:
            assert not s['onfi_events'] and not s['onfi_ns']
    host, = records(after, 'host_diag')
    assert host['write_attempts'] == host['buffer_retries'] + host['writes']
    trace = records(folder / 'measure.trace', 'nand_event')
    windows = records(folder / 'measure.trace', 'nand_window')
    assert len(trace) == sum(s['recorded'] for s in windows)
    for e in trace:
        assert sum(e[k] for k in STAGES) == e['end'] - e['start']
        assert e['lun_ns'] == e['lun_ready'] - e['start']
        assert e['input_ns'] == e['input_ready'] - e['lun_ready']
        assert e['onfi_ns'] == e['onfi_ready'] - e['input_ready']
        if e['onfi_ns']:
            assert onfi and e['op'] == 1 and e['blocker_seq']
            assert e['onfi_ready'] == e['blocker_end'] > e['input_ready']
            assert e['blocker_seq'] < e['seq']
    return stats, hist, trace
