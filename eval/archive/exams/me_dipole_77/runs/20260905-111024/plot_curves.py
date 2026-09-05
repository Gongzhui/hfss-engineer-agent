import csv
import sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator

p = Path(sys.argv[1])
rows = list(csv.DictReader(p.open(encoding='utf-8-sig')))
plt.rcParams.update({'font.family': 'serif', 'font.serif': ['Times New Roman', 'DejaVu Serif'], 'mathtext.fontset': 'dejavuserif', 'axes.linewidth': 2.4})
fig, ax = plt.subplots(figsize=(11, 7))
ax.set_prop_cycle(color=list(plt.get_cmap('tab20').colors))
groups = {}
for row in rows:
    groups.setdefault(row.get('variation', p.stem), []).append(row)
for label, curve in groups.items():
    f = [float(r['freq_ghz']) for r in curve]
    if 's11_db' in curve[0]:
        ax.plot(f, [float(r['s11_db']) for r in curve], lw=2.1, label=label)
    else:
        ax.plot(f, [float(r['re']) for r in curve], lw=2.1, label='R '+label)
        ax.plot(f, [float(r['im']) for r in curve], lw=2.1, ls='--', label='X '+label)
ax.axvline(77, color='black', lw=1.2, ls=':')
if 's11_db' in rows[0]:
    ax.axhline(-10, color='black', lw=1.2, ls='--')
    ax.set_ylabel(r'$S_{11}$ (dB)', fontsize=22)
else:
    ax.axhline(0, color='gray', lw=1)
    ax.set_ylabel('Impedance (Ohm)', fontsize=22)
ax.set_xlabel('Frequency (GHz)', fontsize=22)
ax.set_title(p.stem, fontsize=18)
ax.tick_params(which='both', direction='in', top=True, right=True, labelsize=17)
ax.tick_params(which='major', length=8, width=2)
ax.tick_params(which='minor', length=5, width=1.4)
ax.xaxis.set_minor_locator(AutoMinorLocator())
ax.yaxis.set_minor_locator(AutoMinorLocator())
ax.grid(which='major', color='#5f5f5f', alpha=.42, lw=.8)
ax.grid(which='minor', color='#9a9a9a', alpha=.28, lw=.55, ls='--')
ax.legend(fontsize=10.5 if len(groups)>4 else 15, fancybox=False, edgecolor='black', facecolor='white', loc='best')
fig.tight_layout()
fig.savefig(p.with_suffix('.png'), dpi=160)
print(p.with_suffix('.png'))
