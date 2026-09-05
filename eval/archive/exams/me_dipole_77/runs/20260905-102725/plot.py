import csv,sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator
p=Path(sys.argv[1]); rows=list(csv.DictReader(p.open(encoding='utf-8-sig')))
plt.rcParams.update({'font.family':['Times New Roman','DejaVu Serif'],'mathtext.fontset':'dejavuserif','axes.labelsize':22,'axes.titlesize':18,'xtick.labelsize':17,'ytick.labelsize':17,'legend.fontsize':15,'axes.linewidth':2.4})
fig,ax=plt.subplots(figsize=(10,7)); groups={}
for r in rows: groups.setdefault(r.get('variation','nominal'),[]).append(r)
for label,rs in groups.items():
    x=[float(r['freq_ghz']) for r in rs]
    if 's11_db' in rs[0]: ax.plot(x,[float(r['s11_db']) for r in rs],lw=2.1,label=label)
    else:
        ax.plot(x,[float(r['re']) for r in rs],lw=3,label='Resistance')
        ax.plot(x,[float(r['im']) for r in rs],'--',lw=2.1,label='Reactance')
ax.set(xlabel='Frequency (GHz)',ylabel='S11 (dB)' if 's11_db' in rows[0] else 'Impedance (Ohm)',title=p.stem)
if 's11_db' in rows[0]: ax.axhline(-10,color='black',ls='--'); ax.axvline(77,color='gray',ls=':')
ax.xaxis.set_minor_locator(AutoMinorLocator());ax.yaxis.set_minor_locator(AutoMinorLocator())
ax.tick_params(which='both',direction='in',top=True,right=True);ax.tick_params(which='major',length=8,width=2);ax.tick_params(which='minor',length=5,width=1.4)
ax.grid(which='major',color='#5f5f5f',alpha=.42,lw=.8);ax.grid(which='minor',color='#9a9a9a',alpha=.28,lw=.55,ls='--')
if len(groups)<5: ax.legend(fancybox=False,edgecolor='black')
fig.tight_layout();fig.savefig(p.with_suffix('.png'),dpi=160)
