#!/usr/bin/env python3
"""Standalone plots for validated ONFI diagnostics (no simulated plot data)."""
import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('report',type=Path)
    a=ap.parse_args(); p=a.report
    fio=read(p/'aggregate.csv')
    d=read(p/'breakdown_aggregate.csv')
    f={(r['case'],r['group']):r for r in fio}
    b={(r['case'],r['group'],int(r['op'])):r for r in d}
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':150})
    def save(fig,name):
        fig.savefig(p/(name+'.png'),bbox_inches='tight')
        svg=p/(name+'.svg')
        fig.savefig(svg,bbox_inches='tight')
        svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
        plt.close(fig)

    cases=['4k-r100-qd32','4k-r0-qd32','4k-r70-qd32','4k-r50-qd32','4k-r30-qd32','4k-r50-qd1','32k-r50-qd32','32k-r50-qd1']
    cases=[c for c in cases if (c,'A') in f]
    fig,ax=plt.subplots(figsize=(11,4.5)); x=np.arange(len(cases)); width=.36
    for group,offset,color in [('A',-width/2,'#4c78a8'),('B',width/2,'#e45756')]:
        ax.bar(x+offset,[float(f[c,group]['total_MiB_s']) for c in cases],width,
               yerr=[float(f[c,group]['total_MiB_s_stdev']) for c in cases],capsize=3,
               color=color,label='ONFI '+('OFF' if group=='A' else 'ON'))
    ax.set_xticks(x,[c.replace('-','\n') for c in cases]); ax.set_ylabel('Total throughput (MiB/s)')
    ax.set_title('Same fio workload and volume; FAST off; mean +/- sample SD')
    ax.legend(); ax.grid(axis='y',alpha=.2); fig.tight_layout(); save(fig,'throughput')

    qds=[q for q in (1,2,4,8,16,32,64) if (f'4k-r50-qd{q}','A') in f]
    fig,axes=plt.subplots(1,3,figsize=(13,3.8))
    for group,color in [('A','#4c78a8'),('B','#e45756')]:
        label='ONFI '+('OFF' if group=='A' else 'ON')
        for ax,key,ylabel,scale in [(axes[0],'total_MiB_s','MiB/s',1),(axes[1],'read_mean_us','Mean read latency (us)',1)]:
            ax.errorbar(qds,[float(f[f'4k-r50-qd{q}',group][key])*scale for q in qds],
                        yerr=[float(f[f'4k-r50-qd{q}',group][key+'_stdev'])*scale for q in qds],
                        marker='o',color=color,label=label,capsize=2)
            ax.set_ylabel(ylabel)
        axes[2].plot(qds,[100*int(b[f'4k-r50-qd{q}',group,1]['onfi_events'])/max(1,int(b[f'4k-r50-qd{q}',group,1]['ops'])) for q in qds],marker='o',color=color,label=label)
    for ax in axes:
        ax.set_xscale('log',base=2); ax.set_xticks(qds,[str(q) for q in qds]); ax.set_xlabel('Queue depth'); ax.grid(alpha=.2)
    axes[2].set_ylabel('Programs with an ONFI wait (%)'); axes[0].legend()
    fig.suptitle('4 KiB uniform random 50/50: concurrency sweep'); fig.tight_layout(); save(fig,'qd_sweep')

    mixed=[c for c in ('4k-r70-qd32','4k-r50-qd32','4k-r30-qd32','32k-r50-qd32') if (c,'A') in f]
    stage=[('lun_ns','#4c78a8','Same-LUN queue'),('input_ns','#72b7b2','Shared input gate'),
           ('onfi_ns','#e45756','ONFI extra wait'),('array_ns','#f2cf5b','NAND array'),
           ('channel_late_ns','#b279a2','Late dispatch clamp'),('channel_queue_ns','#ff9da6','Channel queue'),
           ('channel_service_ns','#54a24b','Channel service'),('pcie_tail_ns','#9d755d','PCIe exposed tail')]
    fig,axes=plt.subplots(2,1,figsize=(11,7),sharex=True)
    labels=[c+'\n'+g for c in mixed for g in ('A','B')]
    x=np.arange(len(labels))
    for op,ax in enumerate(axes):
        bottom=np.zeros(len(labels))
        for key,color,label in stage:
            values=np.array([float(b[c,g,op][key+'_mean_us']) for c in mixed for g in ('A','B')])
            ax.bar(x,values,bottom=bottom,color=color,label=label,width=.72); bottom+=values
        ax.set_ylabel('NAND '+('read' if op==0 else 'program')+' (us/op)')
        ax.grid(axis='y',alpha=.2)
    axes[1].set_xticks(x,labels,fontsize=8)
    axes[0].legend(ncol=4,fontsize=8,loc='upper left',bbox_to_anchor=(0,1.28))
    fig.suptitle('Modeled NAND-command latency partition; A=OFF, B=ON',y=1.02)
    fig.tight_layout(); save(fig,'nand_breakdown')

    fig,ax=plt.subplots(figsize=(9,4)); bottom=np.zeros(len(mixed))
    for key,color,label in [('blocker_queued_ns','#4c78a8','Blocking read: before sensing'),
                            ('blocker_sense_ns','#f2cf5b','Blocking read: sensing'),
                            ('blocker_output_ns','#54a24b','Blocking read: output path')]:
        values=np.array([100*int(b[c,'B',1][key])/max(1,int(b[c,'B',1]['onfi_ns'])) for c in mixed])
        ax.bar(range(len(mixed)),values,bottom=bottom,label=label,color=color)
        for i,v in enumerate(values):
            if v>8: ax.text(i,bottom[i]+v/2,f'{v:.1f}%',ha='center',va='center')
        bottom+=values
    ax.set_xticks(range(len(mixed)),mixed); ax.set_ylim(0,100)
    ax.set_ylabel('Share of direct ONFI wait time (%)')
    ax.set_title('Waiting for the other LUN: full observation window')
    ax.legend(loc='upper left',bbox_to_anchor=(0,1.26),ncol=3,fontsize=8)
    fig.tight_layout(); save(fig,'onfi_wait_composition')

    if (p/'trace_example.csv').exists():
        samples=read(p/'trace_example.csv'); origin=min(int(r['start']) for r in samples)
        fig,ax=plt.subplots(figsize=(11,3.6)); present=set()
        colors={'Same-LUN queue':'#4c78a8','Input gate':'#72b7b2','ONFI wait':'#e45756',
                'Array':'#f2cf5b','Data path (incl. queue)':'#54a24b','PCIe tail':'#9d755d'}
        for index,r in enumerate(samples):
            segments=[('Same-LUN queue','start','lun_ready'),('Input gate','lun_ready','input_ready'),
                      ('ONFI wait','input_ready','onfi_ready'),('Array','array_start','array_end'),
                      ('Data path (incl. queue)','data_start','data_end')]
            if int(r['op'])==0: segments.append(('PCIe tail','data_end','end'))
            for label,start,end in segments:
                left,right=(int(r[start])-origin)/1000,(int(r[end])-origin)/1000
                if right<=left: continue
                ax.barh(index,right-left,left=left,height=.55,color=colors[label],
                        label=label if label not in present else None)
                present.add(label)
            ax.text((int(r['end'])-origin)/1000+4,index,f"seq {r['seq']}",va='center',fontsize=8)
        ax.set_yticks(range(3),[r['role'].replace('_',' ')+'\n'+f"ch{r['channel']}/LUN{r['lun']}" for r in samples])
        for first,second,key in [(0,1,'data_end'),(1,2,'end')]:
            x=(int(samples[first][key])-origin)/1000
            ax.annotate('',xy=(x,second-.29),xytext=(x,first+.29),
                        arrowprops={'arrowstyle':'->','color':'#333333','lw':1.2})
        ax.invert_yaxis(); ax.set_xlabel('Modeled time relative to earliest command (us)')
        ax.set_title('An observed read -> ONFI-delayed program -> same-LUN read chain')
        ax.legend(ncol=3,fontsize=8,loc='upper left',bbox_to_anchor=(0,-.26))
        ax.grid(axis='x',alpha=.2); fig.tight_layout(); save(fig,'blocking_chain')
    figures=[('throughput','原八种配置的总吞吐，误差线为三次独立重建的样本标准差。'),
             ('qd_sweep','4 KiB、读写各半的队列深度扫描：吞吐、读平均延迟、program 触发 ONFI 的比例。'),
             ('nand_breakdown','每条 NAND 命令的平均模型时延分解，A=ONFI关、B=ONFI开；不是应用墙钟时间分摊。'),
             ('onfi_wait_composition','直接 ONFI 等待内部的完整时间划分，使用全量计数，而非采样窗口。')]
    if (p/'trace_example.csv').exists():
        figures.append(('blocking_chain','真实随机 fio 中捕获的阻塞链。数据阶段将通道传输与排队合并展示；箭头顺序由命令序号和依赖关联确认。'))
    lines=['# ONFI 实验图表','', '[详细报告与完整表格](SUMMARY.md)。图中 A/B 两组均关闭 FAST。','']
    for name,caption in figures:
        lines += [caption,'',f'![{name}]({name}.png)','',f'[可缩放 SVG]({name}.svg)','']
    (p/'FIGURES.md').write_text('\n'.join(lines).rstrip()+'\n')
    summary=p/'SUMMARY.md'
    if '](FIGURES.md)' not in summary.read_text():
        summary.write_text(summary.read_text()+'\n[吞吐、队列深度、阶段分解与真实阻塞链图表](FIGURES.md)。\n')
    print(p)

if __name__=='__main__':
    main()
