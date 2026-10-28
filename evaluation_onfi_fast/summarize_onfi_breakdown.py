#!/usr/bin/env python3
"""Audit and report the ONFI-only fio timing decomposition and blocking pattern."""
import argparse
import csv
import json
from pathlib import Path
import statistics as st
import subprocess
import sys

from nand_diagnostics import STAGES, records, validate
from summarize_applications import write_csv

def read_csv(path):
    with path.open() as f:
        return list(csv.DictReader(f))

def quantile_bucket(hist, field, percentile):
    total = sum(h[field] for h in hist)
    if not total:
        return '—'
    acc = 0
    for h in sorted(hist, key=lambda x:x['bin']):
        acc += h[field]
        if acc >= total * percentile:
            b = h['bin']
            return '(0,1]' if b == 0 else f'>{2**18}' if b == 19 else f'({2**(b-1)},{2**b}]'
    raise AssertionError('histogram quantile')

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('result', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    m = json.loads((a.result/'manifest.json').read_text())
    repeats = len({i['repeat'] for i in m['plan']})
    assert m['status']=='passed' and m['diagnostics'] and m['groups']==['A','B']
    assert not m['infer_overwrite'] and all(i['placement']==0 for i in m['plan'])
    subprocess.run([sys.executable, str(Path(__file__).with_name('summarize_fio.py')),
                    str(a.result), '--output', str(a.output)], check=True)
    (a.output/'FIO_RESULTS.md').write_text((a.output/'SUMMARY.md').read_text())
    fio = read_csv(a.output/'aggregate.csv')
    lookup = {(r['case'],r['group']):r for r in fio}
    trials = read_csv(a.output/'trials.csv')
    by_die, hist_rows, host_rows, pattern_rows, examples = [], [], [], [], []
    for item in m['plan']:
        folder = a.result/f"r{item['repeat']}"/item['group']/item['case']
        result = validate(folder, item['diagnostics'], item['onfi'])
        if not result:
            continue
        stats, hist, trace = result
        identity = {k:item[k] for k in ('case','group','repeat')}
        by_die += [identity | r for r in stats]
        hist_rows += [identity | r for r in hist]
        host, = records(folder/'measure.after.stats','host_diag')
        host_rows.append(identity | host)
        hit = [e for e in trace if e['onfi_ns']]
        after_program = [e for e in trace if e['op']==0 and e['previous_op']==1 and e['lun_ns']]
        pattern_rows.append(identity | {'trace_entries':len(trace), 'programs':sum(e['op']==1 for e in trace),
            'blocked_programs':len(hit), 'cross_lun_blocks':sum(e['lun']!=e['blocker_lun'] for e in hit),
            'blocker_not_yet_sensing':sum(e['input_ready']<e['blocker_array_start'] for e in hit),
            'read_wait_after_program':len(after_program),
            'mean_read_wait_after_program_us':st.mean(e['lun_ns']/1000 for e in after_program) if after_program else 0})
        if item['case']=='4k-r50-qd32' and item['group']=='B' and item['repeat']==1:
            indexed = {(e['channel'],e['seq']):e for e in trace}
            triples = []
            for nxt in after_program:
                w = indexed.get((nxt['channel'],nxt['previous_seq']))
                if not w or not w['onfi_ns']:
                    continue
                r = indexed.get((w['channel'],w['blocker_seq']))
                if r:
                    triples.append((r,w,nxt))
            if triples:
                triples.sort(key=lambda t:t[1]['onfi_ns'])
                selected = triples[len(triples)//2]
                examples = [identity | {'role':role} | e for role,e in zip(('blocking_read','blocked_program','following_read'), selected)]
    write_csv(a.output/'breakdown_by_die.csv',by_die)
    write_csv(a.output/'host_trials.csv',host_rows)
    write_csv(a.output/'trace_patterns.csv',pattern_rows)
    if examples:
        write_csv(a.output/'trace_example.csv',examples)
    cases = list(dict.fromkeys(i['case'] for i in m['plan'] if i['diagnostics']))
    keys = [k for k in by_die[0] if k not in ('case','group','repeat','channel','lun','op')]
    sums, per_trial, pooled_hist, hosts = [], [], [], []
    for case in cases:
        for group in ('A','B'):
            h = [r for r in host_rows if r['case']==case and r['group']==group]
            hosts.append({'case':case,'group':group} | {k:sum(r[k] for r in h) for k in h[0] if k not in ('case','group','repeat')})
            for op in (0,1):
                selected = [r for r in by_die if r['case']==case and r['group']==group and r['op']==op]
                def combine(sub, identity):
                    s = identity | {k:sum(r[k] for r in sub) for k in keys}
                    s.update({k+'_mean_us':s[k]/s['ops']/1000 if s['ops'] else 0 for k in STAGES+('total_ns',)})
                    return s
                sums.append(combine(selected,{'case':case,'group':group,'op':op}))
                for repeat in sorted({r['repeat'] for r in selected}):
                    per_trial.append(combine([r for r in selected if r['repeat']==repeat],{'case':case,'group':group,'op':op,'repeat':repeat}))
                for b in range(20):
                    selected_h = [r for r in hist_rows if r['case']==case and r['group']==group and r['op']==op and r['bin']==b]
                    pooled_hist.append({'case':case,'group':group,'op':op,'bin':b} | {k:sum(r[k] for r in selected_h) for k in ('onfi','same_lun','total')})
    write_csv(a.output/'breakdown_trials.csv',per_trial)
    write_csv(a.output/'breakdown_aggregate.csv',sums)
    write_csv(a.output/'histograms.csv',pooled_hist)
    write_csv(a.output/'host_aggregate.csv',hosts)
    diag = {(r['case'],r['group'],r['op']):r for r in sums}
    differences=[]
    for case in cases:
        for op in (0,1):
            x,y=diag[case,'A',op],diag[case,'B',op]
            differences.append({'case':case,'op':op} | {k+'_delta_us':y[k+'_mean_us']-x[k+'_mean_us'] for k in STAGES+('total_ns',)})
    write_csv(a.output/'breakdown_deltas.csv',differences)
    channels=[]
    for case in cases:
        for group in ('A','B'):
            for channel in range(4):
                selected=[r for r in by_die if r['case']==case and r['group']==group and r['channel']==channel and r['op']==1]
                channels.append({'case':case,'group':group,'channel':channel,
                    'programs':sum(r['ops'] for r in selected),
                    'onfi_events':sum(r['onfi_events'] for r in selected),
                    'read_lun0_to_program_lun1':sum(r['cross_events'] for r in selected if r['lun']==1),
                    'read_lun1_to_program_lun0':sum(r['cross_events'] for r in selected if r['lun']==0),
                    'same_lun_events':sum(r['same_events'] for r in selected)})
    write_csv(a.output/'blocking_channels.csv',channels)
    overhead = []
    for case in m['diagnostic_controls']:
        for group in ('A','B'):
            ratios=[]
            for r in trials:
                if r['case']!=case or r['group']!=group:
                    continue
                plain=next(t for t in trials if t['case']==case+'-no-diag' and t['group']==group and t['repeat']==r['repeat'])
                assert (r['read_bytes'],r['write_bytes'])==(plain['read_bytes'],plain['write_bytes'])
                ratios.append(100*(float(r['total_MiB_s'])/float(plain['total_MiB_s'])-1))
            overhead.append({'case':case,'group':group,'profiled_MiB_s':float(lookup[case,group]['total_MiB_s']),
                'plain_MiB_s':float(lookup[case+'-no-diag',group]['total_MiB_s']),
                'paired_change_percent':st.mean(ratios),'paired_change_stdev':st.stdev(ratios) if len(ratios)>1 else 0})
    if overhead:
        write_csv(a.output/'overhead.csv',overhead)
    else:
        (a.output/'overhead.csv').write_text('case,group,profiled_MiB_s,plain_MiB_s,paired_change_percent,paired_change_stdev\n')
    out=['# ONFI 开关：fio 性能、阻塞模式与等待分解','',
         f"全部 {len(m['plan'])} 项通过；其中 {sum(i['diagnostics'] for i in m['plan'])} 项启用观察，{sum(not i['diagnostics'] for i in m['plan'])} 项关闭观察作为开销对照。",
         f"源码 `{m['git_head']}`；开跑工作区：{'干净' if not m['git_status'] else '有改动，见清单 SHA256'}。",
         f"{'冒烟验证，不用于性能结论。' if m['smoke'] else f'正式实验，{repeats} 轮独立重建。'} A=ONFI关，B=ONFI开；FAST placement 与覆盖识别始终关闭。",
         f"16 GiB 物理预留；工作集 {m['working_bytes']/1024**2:g} MiB，每项固定 {m['io_bytes']/1024**2:g} MiB 测量 I/O。",
         '其余配置和口径见 [实验协议](../../ONFI_BREAKDOWN.zh-CN.md)。全范围数据模式验证通过，无 GC。','',
         '## 性能影响','',
         f'吞吐为读写合计 MiB/s，均值 ± {repeats} 次独立重建的样本标准差（单次时不估计，显示 0）。下表为启用观察的对照；无观察的核对结果单列。','',
         '| 配置 | A 吞吐 | B 吞吐 | B/A | 读平均 A→B µs | 读 P99 A→B µs |',
         '|---|---:|---:|---:|---|---|']
    def fmt(v):
        return '—' if v=='' else f'{float(v):.2f}'
    for case in cases:
        x,y=lookup[case,'A'],lookup[case,'B']
        out.append(f"| {case} | {float(x['total_MiB_s']):.2f} ± {float(x['total_MiB_s_stdev']):.2f} | {float(y['total_MiB_s']):.2f} ± {float(y['total_MiB_s_stdev']):.2f} | {100*(float(y['total_MiB_s'])/float(x['total_MiB_s'])-1):+.2f}% | {fmt(x['read_mean_us'])}→{fmt(y['read_mean_us'])} | {fmt(x['read_p99_clat_us'])}→{fmt(y['read_p99_clat_us'])} |")
    out += ['', '每轮各自的 P99 再取均值，不是把所有请求合并后的 P99。全部逐轮吞吐、读写延迟见 [FIO_RESULTS.md](FIO_RESULTS.md)。', '',
            '## 触发频率与直接等待','',
            '下表 B 组的数量/时间为各轮之和。触发率以 NAND program 次数为分母；等待均值仅以触发事件为分母。',
            '分位数为完整运行直方图的桶区间，单位 µs；不把区间上界当作精确 P99。','',
            '| 配置 | program 数 | ONFI 次数 | 触发率 | 单次均值 µs | P50 区间 | P99 区间 | 跨 LUN 比例 |',
            '|---|---:|---:|---:|---:|---|---|---:|']
    for case in cases:
        d=diag[case,'B',1]; h=[r for r in pooled_hist if r['case']==case and r['group']=='B' and r['op']==1]
        n=d['onfi_events']
        out.append(f"| {case} | {d['ops']} | {n} | {100*n/max(1,d['ops']):.2f}% | {d['onfi_ns']/max(1,n)/1000:.2f} | {quantile_bucket(h,'onfi',.5)} | {quantile_bucket(h,'onfi',.99)} | {100*d['cross_events']/n:.2f}% |" if n else f"| {case} | {d['ops']} | 0 | 0.00% | — | — | — | — |")
    out += ['', '4 KiB、QD32、50/50 的各通道阻塞方向如下。每通道只有两个 LUN，因此跨 LUN 事件的另一端唯一确定。',
            '全部配置的通道分布见 [blocking_channels.csv](blocking_channels.csv)。','',
            '| B 组通道 | program 数 | 读 LUN0 阻塞写 LUN1 | 读 LUN1 阻塞写 LUN0 | 同 LUN 直接 ONFI 事件 |',
            '|---|---:|---:|---:|---:|']
    for r in channels:
        if r['case']=='4k-r50-qd32' and r['group']=='B':
            out.append(f"| {r['channel']} | {r['programs']} | {r['read_lun0_to_program_lun1']} | {r['read_lun1_to_program_lun0']} | {r['same_lun_events']} |")
    out += ['', '## NAND 命令阶段分解','',
            '单位：µs/条 NAND 命令，按该类操作数加权。八项严格相加等于 NAND 模型总时延。',
            '这些不是 fio 端到端时延的百分比分摊，也不能把跨请求累计等待换算为应用墙钟损失。',
            '纯写配置中若仍出现少量 NAND read，它们属于进程窗口内的附带读取，不是 fio 配置的读负载；来源未逐请求定位。',
            'INPUT 在 ONFI 关/开时都保留；LATE 表示模拟器较晚处理导致通道请求时间向当前时钟补齐。','',
            '| 配置 | 组 | 操作 | 本 die 排队 | INPUT | ONFI 额外 | 阵列 | LATE | 通道排队 | 通道传输 | PCIe 尾部 | 合计 |',
            '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for d in sums:
        if d['ops']:
            out.append(f"| {d['case']} | {d['group']} | {'read' if d['op']==0 else 'program'} | "+' | '.join(f"{d[k+'_mean_us']:.2f}" for k in STAGES+('total_ns',))+' |')
    out += ['', '## 开启 ONFI 后，增加的时间落在哪一项','',
            '以下为 B−A，单位 µs/条 NAND 命令。正数表示增加，负数表示减少；各项相加得到该类 NAND 平均时延的差。',
            '这是两组平均路径的差值，不是应用墙钟时间的因果百分比分摊。其余包括阵列、通道服务和 PCIe 尾部。','',
            '| 配置 | 操作 | 本 die 排队增量 | INPUT 增量 | ONFI 增量 | 通道 LATE+排队增量 | 其余增量 | 总增量 |',
            '|---|---|---:|---:|---:|---:|---:|---:|']
    for d in differences:
        if d['case'] not in ('4k-r70-qd32','4k-r50-qd32','4k-r30-qd32','32k-r50-qd32'):
            continue
        values=[d['lun_ns_delta_us'],d['input_ns_delta_us'],d['onfi_ns_delta_us'],
                d['channel_late_ns_delta_us']+d['channel_queue_ns_delta_us'],
                d['array_ns_delta_us']+d['channel_service_ns_delta_us']+d['pcie_tail_ns_delta_us'],d['total_ns_delta_us']]
        out.append(f"| {d['case']} | {'read' if d['op']==0 else 'program'} | "+' | '.join(f'{v:+.2f}' for v in values)+' |')
    out += ['', '## ONFI 等待内部：在等对侧读的哪一段','',
            '分母仅为 B 组直接 ONFI 等待 ns。三列是这段等待时间的完整划分，覆盖全观察窗口。',
            '“读尚未 sensing”包括当前模型已经预订的未来读的排队。数据输出列包含输出通道排队。',
            '因此约束成本与模拟器的预订顺序、已有队列相互影响，不能解释为 ONFI 固定增加了相同长度的物理时延。','',
            '| 配置 | 对侧读尚未 sensing | 对侧读 sensing | 对侧读数据输出 | 累计 ONFI ms |',
            '|---|---:|---:|---:|---:|']
    for case in cases:
        d=diag[case,'B',1]
        if d['onfi_ns']:
            out.append(f"| {case} | "+' | '.join(f"{100*d[k]/d['onfi_ns']:.2f}%" for k in ('blocker_queued_ns','blocker_sense_ns','blocker_output_ns'))+f" | {d['onfi_ns']/1e6:.3f} |")
    out += ['', '## 读延迟的传导与写缓冲','',
            '本 die 排队按当前预订的最后一个 NAND 操作分类。after program 表明读在等此前的 program 结束，',
            '它本身不是读请求上的直接 ONFI 计数；其中有多少时间最终由先前 ONFI 引起，不能仅凭此分类做严格因果归因。','',
            '| 配置 | 组 | 读本 die 等待 µs/read | 其中前项为 program | 前项为 read | 缓冲重试次数 | 读触发部分页 flush |',
            '|---|---|---:|---:|---:|---:|---:|']
    for h in hosts:
        d=diag[h['case'],h['group'],0]
        out.append(f"| {h['case']} | {h['group']} | {d['lun_ns']/max(1,d['ops'])/1000:.2f} | {d['after_program_ns']/max(1,d['ops'])/1000:.2f} | {d['after_read_ns']/max(1,d['ops'])/1000:.2f} | {h['buffer_retries']} | {h['read_partial_flushes']} |")
    out += ['', '缓冲重试是尝试次数，不是独立受阻 I/O 数；非 FUA 写在进入写缓冲后确认，program 变慢不要求 fio 写延迟同步增加。', '',
            '## 真实阻塞链样本','',
            f"每通道跳过前 {m['trace_skip']} 条观察命令，再保留 {m['trace_limit']} 条；完整观测计数不受该采样窗口限制。",
            '下面从 r1/B/4k-r50-qd32 的窗口内选择存在完整 read→program→read 关联的样本，按直接 ONFI 等待排序取中位项。',
            '这些事件来自普通均匀随机 fio，没有指定 die 地址或人为安排交替序列。',
            '这是解释机制的实际样本，不是最坏情况，也不代表全运行的中位 I/O。']
    if examples:
        origin=min(e['start'] for e in examples)
        out += ['', '| 角色 | channel/LUN | 命令序号 | 提交模型时刻 µs | 本 die 排队 µs | ONFI µs | sensing/program 起→止 µs | 数据阶段结束 µs |',
                '|---|---|---:|---:|---:|---:|---|---:|']
        for e in examples:
            out.append(f"| {e['role']} | {e['channel']}/{e['lun']} | {e['seq']} | {(e['start']-origin)/1000:.3f} | {e['lun_ns']/1000:.3f} | {e['onfi_ns']/1000:.3f} | {(e['array_start']-origin)/1000:.3f}→{(e['array_end']-origin)/1000:.3f} | {(e['data_end']-origin)/1000:.3f} |")
        out += ['', '时刻相对于该三条记录最早的 NAND 模型请求时间；主机提交时间和 CPU 执行时间不等于此时刻。',
                '第一条读的输出结束界定第二条 program 的 ONFI 屏障；第三条读的 previous_seq 指向该 program，并等待它在同 die 完成。',
                '[完整字段](trace_example.csv)；全部窗口模式计数见 [trace_patterns.csv](trace_patterns.csv)，全量窗口事件在原始归档的 measure.trace 中。']
    else:
        out += ['', '本批次未捕获满足三条关联条件的窗口样本；未构造替代数据。']
    out += ['', '## 观察开销对照','',
            '同一轮、同组、同配置穿插开/关诊断。变化列为各轮配对吞吐变化的均值 ± 样本标准差。',
            '主性能结果和细分计数需结合本表判断，不用观察关闭后的吞吐拼接观察开启后的绝对时延。','',
            '| 配置 | 组 | 关闭观察 MiB/s | 开启观察 MiB/s | 配对变化 |',
            '|---|---|---:|---:|---:|']
    for r in overhead:
        out.append(f"| {r['case']} | {r['group']} | {r['plain_MiB_s']:.2f} | {r['profiled_MiB_s']:.2f} | {r['paired_change_percent']:+.2f}% ± {r['paired_change_stdev']:.2f}% |")
    out += ['', '## 数据与验证','',
            '- [逐轮性能及全部对照](FIO_RESULTS.md)、[性能 CSV](trials.csv)、[源码与命令清单](source_manifest.json)。',
            '- [逐 die/操作分解](breakdown_by_die.csv)、[逐轮分解](breakdown_trials.csv)、[聚合分解](breakdown_aggregate.csv)、[阶段增量](breakdown_deltas.csv)、[直方图](histograms.csv)。',
            '- [主机与缓冲计数](host_trials.csv)、[观察开销](overhead.csv)、[原始日志归档](raw-results.tar.gz)、[文件 SHA256](raw_inventory.csv)。',
            '- 每条采样命令和每组完整计数均通过阶段守恒校验；ONFI 等待与原计数一致；观察的 NAND 操作数与 FTL 计数一致。',
            '- FAST 两项开关关闭，无提示、无拒绝 I/O、无 GC；同配置同轮 A/B 读写量相同，所有数据模式校验通过。',
            '- 原始结果覆盖 fio 进程窗口，额外后台读取未按来源过滤；模型时延不含全部主机软件开销。',
            f'- 当前为 {repeats} 次独立重建，不对小幅差异宣称统计显著性；这是有限 I/O 量的隔离实验，不是持续 GC 稳态。']
    center='4k-r50-qd32'
    if center in cases:
        ra,rb=diag[center,'A',0],diag[center,'B',0]
        pa,pb=diag[center,'A',1],diag[center,'B',1]
        delta_read=rb['total_ns_mean_us']-ra['total_ns_mean_us']
        delta_lun=rb['lun_ns_mean_us']-ra['lun_ns_mean_us']
        delta_program=pb['total_ns_mean_us']-pa['total_ns_mean_us']
        findings=['## 关键解释','',
            f"4 KiB、QD32、50/50 中，ONFI 使吞吐从 {float(lookup[center,'A']['total_MiB_s']):.2f} 降到 {float(lookup[center,'B']['total_MiB_s']):.2f} MiB/s。",
            f"NAND read 平均时延增加 {delta_read:.2f} µs，其中本 die 排队项增加 {delta_lun:.2f} µs；",
            f"NAND program 平均时延增加 {delta_program:.2f} µs，其中直接 ONFI 项增加 {pb['onfi_ns_mean_us']:.2f} µs。",
            '读请求没有直接的 ONFI program 等待计数，但会等待被推迟的 program，以及排在它后面的其他读。',
            '样本时间线核对到了同 target 的“读阻塞另一 LUN 的 program → 该 program 阻塞本 LUN 的后续读”链。', '',
            f"本配置 {100*pb['onfi_events']/max(1,pb['ops']):.2f}% 的 program 触发等待，触发时平均等待 {pb['onfi_ns']/max(1,pb['onfi_events'])/1000:.2f} µs。",
            f"其中 {100*pb['blocker_queued_ns']/max(1,pb['onfi_ns']):.2f}% 的累计直接等待发生在阻塞读尚未 sensing 的阶段。",
            '这说明现有资源预订顺序带来的队列会放大 ONFI 成本。该模型对已经预订的未来读保持输出完成屏障，',
            '没有实现重新安排尚未开始的读以给 program 让路；结果应限定为当前 FTL/调度模型，不能当作硬件约束必然造成的固定损失。','']
        if '32k-r50-qd32' in cases:
            wide=diag['32k-r50-qd32','B',1]; wr=diag['32k-r50-qd32','B',0]
            findings += ['主机读写比例也不等于 NAND 操作比例：4 KiB 写会按八个映射页合成一个 32 KiB program，',
                '32 KiB 写则每次即可形成一个 program。',
                f"B 组 4 KiB、50/50 的 NAND read/program 数为 {rb['ops']}/{pb['ops']}（约 {rb['ops']/max(1,pb['ops']):.1f}:1）；",
                f"32 KiB 的计数为 {wr['ops']}/{wide['ops']}（约 {wr['ops']/max(1,wide['ops']):.1f}:1）。",
                '所以两种请求大小的直接冲突率、同 die 排队和性能损失不应只按主机 50/50 比例比较。','']
        if '4k-r30-qd32' in cases:
            high=diag['4k-r30-qd32','B',1]
            findings += [f"4 KiB、QD32、读30% 时，虽然 program 触发比例低于 50/50，但触发次数增加到 {high['onfi_events']}，",
                f"触发时平均等待增至 {high['onfi_ns']/max(1,high['onfi_events'])/1000:.2f} µs；写比例增加意味着更多 program。",
                '判断影响要同时看 program 数、触发概率、单次等待和后续队列，不能只看碰撞率。','']
        if overhead:
            findings += [f"两种 QD32、50/50 配置的观察开销对照，配对吞吐变化均值范围为 {min(r['paired_change_percent'] for r in overhead):+.2f}% 至 {max(r['paired_change_percent'] for r in overhead):+.2f}%。",
                '每项标准差在后表给出；这项检查只覆盖指定两种配置。小幅差异保留，不宣称为零开销。','']
        at=out.index('## 性能影响')
        out[at:at]=findings
    if (a.output/'FIGURES.md').exists():
        out += ['', '[吞吐、队列深度、阶段分解与真实阻塞链图表](FIGURES.md)。']
    (a.output/'SUMMARY.md').write_text('\n'.join(out)+'\n')
    print(a.output/'SUMMARY.md')

if __name__=='__main__':
    main()
