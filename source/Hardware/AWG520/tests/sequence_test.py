# Created on 2/1/20 by gurudev
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from source.Hardware.AWG520.Sequence import Sequence,SequenceList

#import pytest

print('Module name is: ',__name__)
def make_seq():
    wfmdir = Path('../../..') / 'arbpulseshape'
    filestr= str((wfmdir/'test4.txt').resolve())
    #print(str(wfmdir.resolve()))
    #seq='Green,0.01e-7,8e-7\nS2,9e-7,1.7e-6\nWave,9e-7,1.4e-6,Sech\nWave,1.4e-6,1.8e-6,Gauss\nWave,1.8e-6,2.2e-6,' \
    #   'Square\n'+'Wave,2.2e-6,2.6e-6,Lorentz\nWave,2.6e-6,3e-6,Load Wfm,fname='+filestr
    # seq = 'Green,0.01e-6,1e-6'
    #seq = 'Wave,9e-7,1.4e-6\nWave,1e-7,3e-7,Load Wfm,fname='+filestr+'\n'+'Green,1.5e-6,2.5e-6'
    # seq = 'Wave,9e-7+t,1.4e-6+t,Gauss\n'+'Green,1.5e-6,2.5e-6\n'+'S2,5e-7,1.5e-6\n'+'S2,2e-6,2.5e-6\n'
    #        +'Green,3e-6, 3.2e-6\n'+'Measure,1.5e-6,1.8e-6'
    seq = 'Green,1.6e-6,2.5e-6\nWave,1e-6+t,1.5e-6+t,Sech\nMeasure,1.5e-6+t,1.8e-6+t'
    newparams = {'amplitude': 1000.0, 'pulsewidth': 10e-9, 'SB freq': 0.01, 'IQ scale factor': 1.0, 'phase': 0.0,
                 'skew phase':0.0, 'num pulses': 1}
    s = Sequence(seq,pulseparams=newparams,timeres=1.0)
    s.create_sequence(dt=0.1e-6)
    tt = np.linspace(0,s.latest_sequence_event,len(s.c1markerdata))*1e6
    # plt.plot(tt,s.c1m1,'r-',tt,s.c1m2,'g-')
    plt.plot(tt,s.wavedata[0,:],'r-',tt,s.wavedata[1,:],'b-',tt,s.c1markerdata,'g--',tt,s.c2markerdata,'y-')
    #plt.plot(tt,s.wavedata[1,:])
    print(s.c1markerdata[1700:1750])
    plt.show()
    #raise RuntimeError('test the runtime handling')

def make_seq_list():
    wfmdir = Path('../../..') / 'arbpulseshape'
    # print(str(wfmdir.resolve()))
    # notice the sequence below scans time by setting all times after the pulse that is being scanned are also moved
    # seq = 'Green,1.6e-6,2.5e-6\n'Wave,1e-6+t,1.5e-6+t,Sech\n Measure,1.5e-6+t,1.8e-6+t'
    seq = 'S2,1e-6,1.025e-6\n'+'S2,1.03e-6+t,1.05e-6+t\n'+ 'Green,1.05e-6+t,4.025e-6+t\n'+ \
          'Measure,1.025e-6+t,1.125e-6+t'
    #  seq = 'Green,0.0,1e-6'
    newparams = {'amplitude': 100, 'pulsewidth': 50, 'SB freq': 0.01, 'IQ scale factor': 1.0, 'phase': 0.0,
                 'skew phase': 0.0, 'num pulses': 1}
    newscanparams = {'type':'time','start': 0, 'stepsize': 100, 'steps': 3}
    s = SequenceList(seq, pulseparams=newparams, timeres=1,scanparams = newscanparams)
    s.create_sequence_list()
    for nn in list(range(len(s.sequencelist))):
        xstop = s.sequencelist[nn].maxend
        points = len(s.sequencelist[nn].c1markerdata)
        ydat = s.sequencelist[nn].wavedata
        c1dat = s.sequencelist[nn].c1markerdata
        c2dat = s.sequencelist[nn].c2markerdata
        tt = np.linspace(0, xstop, points)
        plt.plot(tt, ydat[0, :], 'r-', tt, ydat[1, :], 'b-', tt, c1dat, 'g--',tt,c2dat,'+')
        plt.show()
    # plt.plot(tt,s.wavedata[1,:])

    # raise RuntimeError('test the runtime handling')

def make_long_seq():
    seq = [['S2','1000','1050'],['Green','100000','102000'],['Measure','100100','100400']]
    newparams = {'amplitude': 100, 'pulsewidth': 50, 'SB freq': 0.01, 'IQ scale factor': 1.0, 'phase': 0.0,
                 'skew phase': 0.0, 'num pulses': 1}
    s = Sequence(seq, pulseparams=newparams, timeres=1)
    s.create_sequence(dt=0)
    tt = np.linspace(0, s.latest_sequence_event, len(s.c1markerdata))
    plt.plot(tt, s.wavedata[0, :], 'r-', tt, s.wavedata[1, :], 'b-', tt, s.c1markerdata, 'g--', tt, s.c2markerdata,
             'y-')
    # plt.plot(tt,s.wavedata[1,:])
    plt.show()
    # raise RuntimeError('test the runtime handling')

def test_sequence():
    make_seq()

def test_seq_list():
    make_seq_list()

if __name__ == '__main__':
    test_sequence()
    # test_seq_list()
    #make_long_seq()