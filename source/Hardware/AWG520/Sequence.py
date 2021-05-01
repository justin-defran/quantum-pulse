# Created by Gurudev Dutt <gdutt@pitt.edu> on 12/24/19
# This code is adapted from Kai Zhang's code and extended to enable arbitrary pulseshapes
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
import sys

import numpy as np
import logging
from pathlib import Path
from typing import List, NewType
from decimal import Decimal, getcontext
from source.Hardware.AWG520.Pulse import Gaussian, Square, Marker, Sech, Lorentzian, LoadWave, Pulse
from source.common.utils import log_with, create_logger, get_project_root
import copy, re,sys

maindir = get_project_root()
seqfiledir = maindir / 'Hardware/sequencefiles/'
pulseshapedir = maindir / 'arbpulseshape/'
# logfiledir = maindir / 'logs/'
# print('the sequence file directory is {0} and log file directory is {1}'.format(seqfiledir.resolve(),logfiledir.resolve()))
modlogger = create_logger('seqlogger')

# unit conversion factors
_GHz = 1.0e9  # Gigahertz
_MHz = 1.0e6  # Megahertz
_us = 1.0e-6  # Microseconds
_ns = 1.0e-9  # Nanoseconds
getcontext().prec = 14  # precision with which values are stored

# keywords used by sequence parser
_MW_S1 = 'S1'  # disconnected for now
_MW_S2 = 'S2'  # channel 1, marker 1
_GREEN_AOM = 'Green'  # ch1, marker 2
_ADWIN_TRIG = 'Measure'  # ch2, marker 2
_WAVE = 'Wave'  # channel 1 and 2, analog I/Q data
_BLANK = 'Blank'  # new keyword which turns off all channels, to be implemented
_FULL = 'Full'  # new keyword which turns on all channels high, to be implemented
_MARKER = 'Marker'  # new keyword for any marker
_ANALOG1 = 'Analog1'  # new keyword for channel 1
_ANALOG2 = 'Analog2'  # new keyword for channel 2
# dictionary of connections from marker channels to devices,
_CONN_DICT = {_MW_S1: None, _MW_S2: 1, _GREEN_AOM: 2, _ADWIN_TRIG: 4}
# dictionary of IQ parameters that will be used as default if none is supplied
_PULSE_PARAMS = {'amplitude': 0.0, 'pulsewidth': 20, 'SB freq': 0.00, 'IQ scale factor': 1.0,
                 'phase': 0.0, 'skew phase': 0.0, 'num pulses': 1}
# allowed values of the Waveform types
_PULSE_TYPES = ['Gauss', 'Sech', 'Square', 'Lorentz', 'Load Wfm']

_IQTYPE = np.dtype('<f4')  # AWG520 stores analog values as 4 bytes in little-endian format
_MARKTYPE = np.dtype('<i1')  # AWG520 stores marker values as 1 byte


def to_int(iterable):
    return [int(x) for x in iterable]


class SequenceEvent:
    """A single sequence event.
    :param event_type: The type of event, e.g. Marker or Wave etc
    :param start: The start time of the event.
    :param stop: The stop time of the event.
    :param start_increment: The multiplier for incrementing the start time.
    :param stop_increment: The multiplier for incrementing the stop time.
    :param sampletime: the sampling time (clock rate) used for this event
    """
    _counter = 0  # class variable keeps track of how many sequence events are there

    def __init__(self, event_type='', start=1.0 * _us, stop=1.1 * _us, start_increment=0.0, stop_increment=0.0,
                 sampletime=1.0 * _ns):
        SequenceEvent._counter += 1  # increment whenever a new event is created
        self.eventidx = SequenceEvent._counter  # publicly accessible value of the event id
        self.__event_type = event_type
        self.__start = start
        self.__stop = stop
        self.__start_increment = start_increment
        self.__stop_increment = stop_increment
        self.increment_time(dt=0.0)
        self.__duration = self.stop - self.start
        self.__sampletime = sampletime
        # these variables store the start, stop, and duration in units of the sampletime, useful for indexing arrays
        # and writing data to the AWG
        self.__t1_idx = round(Decimal(self.start / self.sampletime))
        self.__t2_idx = round(Decimal(self.stop / self.sampletime))
        self.__dur_idx = round(Decimal(self.duration / self.sampletime))
        # data for the event
        self.data = None

    @property
    def event_type(self):
        return self.__event_type

    @event_type.setter
    def event_type(self, var):
        try:
            if type(var) == str:
                self.__event_type = var
            else:
                raise TypeError("Event type must be string")
        except TypeError as err:
            modlogger.error("Type error {0}".format(err))

    @property
    def start(self):
        return self.__start

    @start.setter
    def start(self, var):
        try:
            if type(var) == float or type(var) == int:
                self.__start = float(var)
            else:
                raise TypeError('start time must be a floating point number or integer')
        except TypeError as err:
            modlogger.error("Type error {0}".format(err))

    @property
    def stop(self):
        return self.__stop

    @stop.setter
    def stop(self, var):
        try:
            if type(var) == float or type(var) == int:
                self.__stop = float(var)
            else:
                raise TypeError('stop time must be a floating point number or integer')
        except TypeError as err:
            modlogger.error("Type error {0}".format(err))

    @property
    def start_increment(self):
        return self.__start_increment

    @start_increment.setter
    def start_increment(self, var):
        try:
            if type(var) == float or type(var) == int:
                self.__start_increment = float(var)
            else:
                raise TypeError('start increment must be a floating point number or integer')
        except TypeError as err:
            modlogger.error("Type error {0}".format(err))

    @property
    def stop_increment(self):
        return self.__stop_increment

    @stop_increment.setter
    def stop_increment(self, var):
        try:
            if type(var) == float or type(var) == int:
                self.__stop_increment = float(var)
            else:
                raise TypeError('stop increment must be a floating point number or integer')
        except TypeError as err:
            modlogger.error("Type error {0}".format(err))

    @property
    def duration(self):
        return self.__duration

    @duration.setter
    def duration(self, var):
        try:
            if type(var) == float or type(var) == int:
                self.__duration = float(var)  # duration is kept as a floating point number for easy manipulation
            else:
                raise TypeError('duration must be a floating point number or integer')
        except TypeError as err:
            modlogger.error("Type error {0}".format(err))

    @property
    def sampletime(self):
        return self.__sampletime

    @sampletime.setter
    def sampletime(self, var):
        try:
            if type(var) == float or type(var) == int:
                self.__sampletime = float(var)
            else:
                raise TypeError('sample time must be a floating point number or integer')
        except TypeError as err:
            modlogger.error("Type error {0}".format(err))

    @property
    def t1_idx(self):  # this variable stores the start time in integer format suitable for indexing arrays
        self.__t1_idx = round(Decimal(self.start / self.sampletime))
        return self.__t1_idx

    @property
    def t2_idx(self):  # this variable stores the stop time in integer format suitable for indexing arrays
        self.__t2_idx = round(Decimal(self.stop / self.sampletime))
        return self.__t2_idx

    @property
    def dur_idx(self):  # this variable stores the start time in integer format suitable for indexing arrays
        self.__dur_idx = round(Decimal(self.duration / self.sampletime))
        return self.__dur_idx

    def increment_time(self, dt: float = 0):
        """Increments the start and stop times by dt.
        :param dt: The time increment.
        """
        # dt = round(Decimal(dt / self.sampletime))
        dt = float(dt)  # convert to decimal to allow arithmetic
        self.start += dt * self.start_increment
        self.stop += dt * self.stop_increment


class WaveEvent(SequenceEvent):
    """ Provides functionality for events that are analog in nature. Inherits from :class:`sequence event <SequenceEvent>`
    :param pulse_params: A dictionary containing parameters for the IQ modulator: amplitude, pulseWidth,
                        SB frequency, IQ scale factor, phase, skewPhase.
    :param pulse_type: type of pulse desired, eg Gauss, Sech etc
    """
    # these 2 class variables keep track of the class type and the number of instances
    EVENT_KEYWORD = "Wave"
    _wavecounter = 0

    def __init__(self, start=1e-6, stop=1.1e-6, pulse_params=None, pulse_type='Gauss', start_inc=0.0, stop_inc=0.0,
                 dt=0.0, sampletime=1.0 * _ns):
        super().__init__(start=1e-6, stop=1.1e-6, start_increment=start_inc, stop_increment=stop_inc,
                         sampletime=sampletime)
        WaveEvent._wavecounter += 1  # increment the wave counter
        self.waveidx = WaveEvent._wavecounter  # publicly accessible id for the wave event
        self.event_type = self.EVENT_KEYWORD
        if pulse_params is None:
            pulse_params = _PULSE_PARAMS
        self.pulse_params = pulse_params
        self.start = start
        self.stop = stop
        self.increment_time(dt)
        self.duration = self.stop - self.start
        self.__pulse_type = pulse_type
        self.extract_pulse_params_from_dict()  # unpack the dictionary of pulse params
        zerosdata = np.zeros(self.dur_idx, dtype=_IQTYPE)  # create an array ofcc zeros of the right size
        pulse = Pulse(self.waveidx, self.dur_idx, self.ssb_freq, self.iqscale,
                      self.phase, self.skewphase)  # create a blank Pulse object
        pulse.iq_generator(zerosdata)
        self.data = np.array((pulse.I_data, pulse.Q_data))  # initialize the data to be zero

    @property
    def pulse_params(self):
        return self.__pulse_params

    @pulse_params.setter
    def pulse_params(self, iqdic):
        try:
            if type(iqdic) == dict:
                self.__pulse_params = iqdic
            else:
                raise TypeError('IQ params must be a dictionary')
        except TypeError as err:
            modlogger.error('Type error: {0}'.format(err))

    @property
    def pulse_type(self):
        return self.__pulse_type

    @pulse_type.setter
    def pulse_type(self, var: str):
        try:
            if type(var) == str:
                if var in _PULSE_TYPES:
                    self.__pulse_type = var
                else:
                    raise TypeError(f'Pulse type must be in list of pulse types allowed:{_PULSE_TYPES}')
            else:
                raise TypeError('pulse type must be of type string')
        except TypeError as err:
            modlogger.error('Type error: {0}'.format(err))

    def extract_pulse_params_from_dict(self):
        """This helper method simply extracts the relevant params from the iq dictionary"""
        self.__ssb_freq = float(self.pulse_params['SB freq']) * _MHz  # SB freq is in units of Mhz
        self.__iqscale = float(self.pulse_params['IQ scale factor'])
        self.__phase = float(self.pulse_params['phase'])
        # TODO: should i divide by sampletime ?
        self.__pulsewidth = int(self.pulse_params['pulsewidth'])
        self.__amp = int(self.pulse_params['amplitude'])  # needs to be a number between 0 and 100
        self.__skew_phase = float(self.pulse_params['skew phase'])
        self.__npulses = self.pulse_params['num pulses']  # not needed for a single WaveEvent

    @property
    def data(self):
        return self.__data

    @data.setter
    def data(self, datarr):
        self.__data = datarr

    @property
    def pulsewidth(self):
        return self.__pulsewidth

    @property
    def ssb_freq(self):
        return self.__ssb_freq

    @property
    def amplitude(self):
        return self.__amp

    @property
    def iqscale(self):
        return self.__iqscale

    @property
    def phase(self):
        return self.__phase

    @property
    def skewphase(self):
        return self.__skew_phase


# TODO: looks to me like we can probably get rid of the Pulse module and move all the data generation here. will make
# it more self-contained.
class GaussPulse(WaveEvent):
    """Generates a Wave event with a Gaussian shape"""
    PULSE_KEYWORD = "Gauss"

    def __init__(self, start=1e-6, stop=1.1e-7, pulse_params=None, start_inc=0, stop_inc=0, dt=0, sampletime=1.0 * _ns):
        super().__init__(start=start, stop=stop, pulse_params=pulse_params, start_inc=start_inc, stop_inc=stop_inc,
                         dt=dt, sampletime=sampletime)
        self.pulse_type = self.PULSE_KEYWORD
        # if duration < 6 * pulsewidth, set it equal to at least that much
        if self.duration < 6 * self.pulsewidth:
            self.duration = 6 * self.pulsewidth
            self.stop = self.start + self.duration
        pulse = Gaussian(self.waveidx, self.dur_idx, self.ssb_freq, self.iqscale, self.phase,
                         self.pulsewidth, self.amplitude, self.skewphase)
        pulse.data_generator()  # generate the data
        self.data = np.array((pulse.I_data, pulse.Q_data))


class SechPulse(WaveEvent):
    """Generates a Wave event with a Sech shape"""
    PULSE_KEYWORD = "Sech"

    def __init__(self, start=1e-6, stop=1.1e-7, pulse_params=None, start_inc=0, stop_inc=0, dt=0, sampletime=1.0 * _ns):
        super().__init__(start=start, stop=stop, pulse_params=pulse_params, start_inc=start_inc, stop_inc=stop_inc,
                         dt=dt, sampletime=sampletime)
        self.pulse_type = self.PULSE_KEYWORD
        if self.duration < 6 * self.pulsewidth:
            self.duration = 6 * self.pulsewidth
            self.stop = self.start + self.duration
        pulse = Sech(self.waveidx, self.dur_idx, self.ssb_freq, self.iqscale, self.phase,
                     self.pulsewidth, self.amplitude, self.skewphase)
        pulse.data_generator()  # generate the data
        self.data = np.array((pulse.I_data, pulse.Q_data))


class SquarePulse(WaveEvent):
    """Generates a Wave event with a Square shape"""
    PULSE_KEYWORD = "Square"

    def __init__(self, start=1e-6, stop=1.1e-7, pulse_params=None, start_inc=0, stop_inc=0, dt=0, sampletime=1.0 * _ns):
        super().__init__(start=start, stop=stop, pulse_params=pulse_params, start_inc=start_inc, stop_inc=stop_inc,
                         dt=dt, sampletime=sampletime)
        self.pulse_type = self.PULSE_KEYWORD
        if self.duration < 6 * self.pulsewidth:
            self.duration = 6 * self.pulsewidth
            self.stop = self.start + self.duration
        pulse = Square(self.waveidx, self.dur_idx, self.ssb_freq, self.iqscale, self.phase, self.amplitude,
                       self.skewphase)
        pulse.data_generator()  # generate the data
        self.data = np.array((pulse.I_data, pulse.Q_data))


class LorentzPulse(WaveEvent):
    """Generates a Wave event with a Lorentzian shape"""
    PULSE_KEYWORD = "Lorentz"

    def __init__(self, start=1e-6, stop=1.1e-7, pulse_params=None, start_inc=0, stop_inc=0, dt=0, sampletime=1.0 * _ns):
        super().__init__(start=start, stop=stop, pulse_params=pulse_params, start_inc=start_inc, stop_inc=stop_inc,
                         dt=dt, sampletime=sampletime)
        self.pulse_type = self.PULSE_KEYWORD
        if self.duration < 6 * self.pulsewidth:
            self.duration = 6 * self.pulsewidth
            self.stop = self.start + float(self.duration)
        pulse = Lorentzian(self.waveidx, self.dur_idx, self.ssb_freq, self.iqscale, self.phase, self.pulsewidth,
                           self.amplitude, self.skewphase)
        pulse.data_generator()  # generate the data
        self.data = np.array((pulse.I_data, pulse.Q_data))


class ArbitraryPulse(WaveEvent):
    """Generates a Wave event with any shape given by numerically generated data read from text file"""
    PULSE_KEYWORD = "Load Wfm"

    def __init__(self, start=1e-6, stop=1.1e-7, pulse_params=None, filename=None, start_inc=0, stop_inc=0, dt=0,
                 sampletime=1.0 * _ns):
        super().__init__(start=start, stop=stop, pulse_params=pulse_params, start_inc=start_inc, stop_inc=stop_inc,
                         dt=dt, sampletime=sampletime)
        if filename is None:
            filename = 'test4.txt'
        self.pulse_type = self.PULSE_KEYWORD
        self.filename = pulseshapedir / filename
        if self.duration < 6 * self.pulsewidth:
            self.duration = 6 * self.pulsewidth
            self.stop = self.start + float(self.duration)
        pulse = LoadWave(self.filename, self.waveidx, self.dur_idx, self.ssb_freq, self.iqscale, self.phase,
                         self.pulsewidth, self.amplitude, self.skewphase)
        pulse.data_generator()  # generate the data
        self.data = np.array((pulse.I_data, pulse.Q_data))


class MarkerEvent(SequenceEvent):
    """ Provides functionality for events that are digital in nature using marker output of AWG
    :param start: start time for marker event
    :param stop: stop time for marker event
    :param connection_dict: dictionary that specifies which markers are connected to which hardware
        """
    # these 2 class variables define the event type and track the number of marker events
    EVENT_KEYWORD = "Marker"
    _markercounter = 0

    def __init__(self, start=1e-6, stop=1.1e-7, connection_dict=None, start_inc=0.0, stop_inc=0.0, dt=0.0,
                 sampletime=1.0 * _ns):
        super().__init__(start=start, stop=stop, event_type=self.EVENT_KEYWORD, start_increment=start_inc,
                         stop_increment=stop_inc, sampletime=sampletime)
        if connection_dict is None:
            connection_dict = _CONN_DICT
        MarkerEvent._markercounter += 1
        self.markeridx = MarkerEvent._markercounter  # public id of the marker event
        self.connection_dict = connection_dict
        self.pulse_type = self.EVENT_KEYWORD
        self.increment_time(dt)
        self.duration = self.stop - self.start
        self.markernum = 0  # default marker num , also ensures zero output
        pulse = Marker(num=self.markeridx, width=self.dur_idx, markernum=0, marker_on=self.t1_idx,
                       marker_off=self.t2_idx)
        pulse.data_generator()
        self.data = pulse.data

    @property
    def data(self):
        return self.__data

    @data.setter
    def data(self, datarr):
        self.__data = datarr


class Green(MarkerEvent):
    """Turns on the green AOM"""
    PULSE_KEYWORD = "Green"

    def __init__(self, start=1e-6, stop=1.1e-7, connection_dict=None, start_inc=0, stop_inc=0, dt=0,
                 sampletime=1.0 * _ns):
        super().__init__(start=start, stop=stop, connection_dict=connection_dict, start_inc=start_inc,
                         stop_inc=stop_inc, dt=dt, sampletime=sampletime)
        if connection_dict is None:
            connection_dict = _CONN_DICT
        self.connection_dict = connection_dict
        self.markernum = self.connection_dict[_GREEN_AOM]
        self.pulse_type = self.PULSE_KEYWORD
        pulse = Marker(num=self.markeridx, width=self.dur_idx, markernum=self.markernum, marker_on=self.t1_idx,
                       marker_off=self.t2_idx)
        pulse.data_generator()
        self.data = pulse.data


class Measure(MarkerEvent):
    """Turns on the Adwin trigger for measurement"""
    PULSE_KEYWORD = "Measure"

    def __init__(self, start=1e-6, stop=1.1e-7, connection_dict=None, start_inc=0, stop_inc=0, dt=0,
                 sampletime=1.0 * _ns):
        super().__init__(start=start, stop=stop, connection_dict=connection_dict, start_inc=start_inc,
                         stop_inc=stop_inc, dt=dt, sampletime=sampletime)
        if connection_dict is None:
            connection_dict = _CONN_DICT
        self.connection_dict = connection_dict
        self.markernum = self.connection_dict[_ADWIN_TRIG]
        self.pulse_type = self.PULSE_KEYWORD
        pulse = Marker(num=self.markeridx, width=self.dur_idx, markernum=self.markernum, marker_on=self.t1_idx,
                       marker_off=self.t2_idx)
        pulse.data_generator()
        self.data = pulse.data


class S1(MarkerEvent):
    """Turns on the MW switch S1"""
    PULSE_KEYWORD = "S1"

    def __init__(self, start=1e-6, stop=1.1e-7, connection_dict=None, start_inc=0, stop_inc=0, dt=0,
                 sampletime=1.0 * _ns):
        super().__init__(start=start, stop=stop, connection_dict=connection_dict, start_inc=start_inc,
                         stop_inc=stop_inc, dt=dt, sampletime=sampletime)
        if connection_dict is None:
            connection_dict = _CONN_DICT
        self.connection_dict = connection_dict
        self.markernum = self.connection_dict[_MW_S1]
        self.pulse_type = self.PULSE_KEYWORD
        pulse = Marker(num=self.markeridx, width=self.dur_idx, markernum=self.markernum, marker_on=self.t1_idx,
                       marker_off=self.t2_idx)
        pulse.data_generator()
        self.data = pulse.data


class S2(MarkerEvent):
    """Turns on the MW switch S2"""
    PULSE_KEYWORD = "S2"

    def __init__(self, start=1e-6, stop=1.1e-7, connection_dict=None, start_inc=0, stop_inc=0, dt=0,
                 sampletime=1.0 * _ns):
        super().__init__(start=start, stop=stop, connection_dict=connection_dict, start_inc=start_inc,
                         stop_inc=stop_inc, dt=dt, sampletime=sampletime)
        if connection_dict is None:
            connection_dict = _CONN_DICT
        self.connection_dict = connection_dict
        self.markernum = self.connection_dict[_MW_S2]
        self.pulse_type = self.PULSE_KEYWORD
        pulse = Marker(num=self.markeridx, width=self.dur_idx, markernum=self.markernum, marker_on=self.t1_idx,
                       marker_off=self.t2_idx)
        pulse.data_generator()
        self.data = pulse.data


class Channel:
    """Provides functionality for a sequence of :class:`sequence events <SequenceEvent>`.
    :param ch_type: type of channel, e.g. Marker or Wave
    :param event_train: A collection of :class:`sequence events <SequenceEvent>`.
    :param delay: Delay in the format [AOM delay, MW delay].
    :param pulse_params: A dictionary containing parameters for the IQ modulator: amplitude, pulseWidth,
                        SB frequency, IQ scale factor, phase, skewPhase.
    :param connection_dict: A dictionary of the connections between AWG channels and switches/IQ modulators.
    :param event_channel_idx: index of event in channel where event train is added
    """

    def __init__(self, ch_type=None, event_train=None, delay=None, pulse_params=None, connection_dict=None,
                 event_channel_idx=0, sampletime=1.0 * _ns):
        if ch_type is None:
            ch_type = _MARKER
        if delay is None:
            delay = [0, 0]
        if pulse_params is None:
            pulse_params = _PULSE_PARAMS
        if connection_dict is None:
            connection_dict = _CONN_DICT
        if event_train is None:
            event_train = []  # add empty event
        self.logger = logging.getLogger('seqlogger.channel')
        self.event_train = event_train
        self.delay = delay
        self.pulse_params = pulse_params
        self.connection_dict = connection_dict
        self.sampletime = sampletime
        # set various object variables
        self.num_of_events = len(self.event_train)  # number of events in the channel
        self.event_channel_index = event_channel_idx  # index of event in channel
        self.latest_channel_event = 0  # channel event with latest time
        self.first_channel_event = 0  # channel event with earliest time
        self.ch_type = ch_type  # type of channel events
        #
        if self.num_of_events == 1 or self.num_of_events == 0:
            self.separation = 0.0
        # array storing all the start and stop times in this channel
        self.event_start_times = []
        self.event_stop_times = []
        self.event_durations = []
        for idx, evt in self.event_train:
            self.event_start_times.append(evt.start)
            self.event_stop_times.append(evt.stop)

        self.set_first_channel_event()
        self.set_latest_channel_event()

    def add_event(self, time_on=1e-6, time_off=1.1e-6, pulse_type="Green", start_inc=0.0, stop_inc=0.0, dt=0.0,
                  fname=None):
        """This method adds one event of a given type to the channel
        :param time_on: starting time of the event
        :param time_off: ending time of the event
        :param pulse_type: type of pulse
        :param start_inc: increment for start time
        :param stop_inc: increment for stop time
        :param dt: increment for start and stop times
        :param fname: filename used for arbitrary pulse shapes
        """
        self.num_of_events += 1
        self.event_channel_index += 1
        event = SequenceEvent()  # no need for this statement, but pycharm complains event may be assigned before ref?
        # TODO: simplify this remaining code using a dictionary or other function reference list and a for loop
        if self.ch_type == "Wave":
            if pulse_type == _PULSE_TYPES[0]:
                event = GaussPulse(start=time_on, stop=time_off, pulse_params=self.pulse_params, start_inc=start_inc,
                                   stop_inc=stop_inc, dt=dt, sampletime=self.sampletime)
            elif pulse_type == _PULSE_TYPES[1]:
                event = SechPulse(start=time_on, stop=time_off, pulse_params=self.pulse_params, start_inc=start_inc,
                                  stop_inc=stop_inc, dt=dt, sampletime=self.sampletime)
            elif pulse_type == _PULSE_TYPES[2]:
                event = SquarePulse(start=time_on, stop=time_off, pulse_params=self.pulse_params, start_inc=start_inc,
                                    stop_inc=stop_inc, dt=dt, sampletime=self.sampletime)
            elif pulse_type == _PULSE_TYPES[3]:
                event = LorentzPulse(start=time_on, stop=time_off, pulse_params=self.pulse_params, start_inc=start_inc,
                                     stop_inc=stop_inc, dt=dt, sampletime=self.sampletime)
            elif pulse_type == _PULSE_TYPES[4]:
                event = ArbitraryPulse(start=time_on, stop=time_off, pulse_params=self.pulse_params,
                                       start_inc=start_inc,
                                       stop_inc=stop_inc, filename=fname, dt=dt, sampletime=self.sampletime)
        elif self.ch_type == "Marker":
            if pulse_type == _GREEN_AOM:
                event = Green(start=time_on, stop=time_off, connection_dict=self.connection_dict, start_inc=start_inc,
                              stop_inc=stop_inc, dt=dt, sampletime=self.sampletime)
            elif pulse_type == _ADWIN_TRIG:
                event = Measure(start=time_on, stop=time_off, connection_dict=self.connection_dict, start_inc=start_inc,
                                stop_inc=stop_inc, dt=dt, sampletime=self.sampletime)
            elif pulse_type == _MW_S1:
                event = S1(start=time_on, stop=time_off, connection_dict=self.connection_dict, start_inc=start_inc,
                           stop_inc=stop_inc, dt=dt, sampletime=self.sampletime)
            elif pulse_type == _MW_S2:
                event = S2(start=time_on, stop=time_off, connection_dict=self.connection_dict, start_inc=start_inc,
                           stop_inc=stop_inc, dt=dt, sampletime=self.sampletime)
        else:
            event = SequenceEvent(start=time_on, stop=time_off, start_increment=start_inc,
                                  stop_increment=stop_inc, sampletime=self.sampletime)
            event.increment_time(dt=dt)
        self.event_train.append(event)
        self.event_start_times.append(event.start)
        self.event_stop_times.append(event.stop)


    def add_event_train(self, time_on=1e-6, time_off=1.1e-6, separation=0.0, events_in_train=1, pulse_type='Gauss',
                        start_inc=0.0, stop_inc=0.0, dt=0.0, fname=None):
        """This method adds multiple events to the channel
        :param time_on: starting time of the event
        :param time_off: ending time of the event
        :param separation: optional separation between the events
        :param events_in_train: number of events to add to the train
        :param pulse_type: type of pulse
        :param start_inc: start increment multiplier
        :param stop_inc: stop increment multiplier
        :param dt: amount to increment
        :param fname: filename for arbitrary pulses
        """
        # add this pulse to the current pulse channel
        self.add_event(time_on=time_on, time_off=time_off, pulse_type=pulse_type, start_inc=start_inc,
                       stop_inc=stop_inc,dt=dt, fname=fname)  # make sure we add the increment first
        width = self.event_train[0].duration
        sep = float(separation)
        if events_in_train > 1:
            for nn in range(events_in_train - 1):
                t_on = time_on + (nn + 1) * (width + sep)
                t_off = time_off + (nn + 1) * (width + sep)
                # no need to add any more increments
                self.add_event(time_on=t_on, time_off=t_off, pulse_type=pulse_type, fname=fname)
        self.set_latest_channel_event()
        self.set_first_channel_event()

    def delete_event(self, index):
        if self.num_of_events > 0:
            evt = self.event_train.pop(index)
            self.num_of_events -= 1
            self.event_channel_index -= 1
            self.set_latest_channel_event()
            self.set_first_channel_event()
            return True
        else:
            return False

    def has_coincident_events(self):
        found_coincident_event = False
        evt_on_times = []
        # evt_off_times = []
        for evt in self.event_train:
            evt_on_times.extend(evt.t1_idx)
        if len(evt_on_times) > len(set(evt_on_times)):
            found_coincident_event = True
        return found_coincident_event

    def set_first_channel_event(self):
        if self.num_of_events > 1:
            self.first_channel_event = sorted(self.event_train, key=lambda x: x.start)[0].start
        elif self.num_of_events == 1:
            self.first_channel_event = self.event_train[0].stop
        else:
            self.first_channel_event = 0
        self.event_start_times.sort()   # we will also keep this array sorted

    def set_latest_channel_event(self):
        self.latest_channel_event = 0
        for i in range(self.num_of_events):
            if self.event_train[i].stop > self.latest_channel_event:
                self.latest_channel_event = self.event_train[i].stop

        self.event_stop_times.sort()


    # def get_event_start_times(self):
    #     for idx, evt in self.event_train:
    #         self.event_start_times.append(evt.t1_idx)
    #     return self.event_start_times

    # def get_event_stop_times(self):
    #     for idx, evt in self.event_train:
    #         self.event_stop_times.append(evt.t2_idx)
    #     return self.event_stop_times
    #
    # def get_event_durations(self):
    #     for idx, evt in self.event_train:
    #         self.event_durations.append(evt.dur_idx)
    #     return self.event_durations

    # @property
    # def first_channel_event(self):
    #     self.__first_channel_event = np.amin(np.array(self.event_start_times))
    #     return self.__first_channel_event
    #
    # @first_channel_event.setter
    # def first_channel_event(self,var):
    #     self.__first_channel_event = var


class Sequence:
    def __init__(self, seqtext=None, delay=None, pulseparams=None, connectiondict=None, timeres=1):
        """Class that implements a collection of :class:`channels <Channel>`
            :param seqtext: string that specifies sequence in the form 'type,start,stop, optionalparams'\n,
            eg. here is Rabi sequence 'S1,1000,1000+t\nGreen,2000+t,5000+t\nMeasure,2000+t,2100+t'
            for a gaussian pulse would use 'Wave,1000,1000+t,Gauss\nGreen,2000+t,5000+t\nMeasure,2000+t,
            2100+t'
            :param delay: list with [AOM delay, MW delay] , possibly other delays to be added.
            :param pulseparams: a dictionary containing the amplitude, pulsewidth,SB frequency,IQ scale factor,
                        phase, skewphase
            :param connectiondict: a dictionary of the connections between AWG channels and switches/IQ modulators
            :param timeres: clock rate in ns

            After creating the instance, call the method create_sequence with an optional increment of time ,
            and then the arrays created will be: wavedata (analag I and Q data), c1markerdata, c2markerdata
        """
        if delay is None:
            delay = [0, 0]
        self.logger = logging.getLogger('seqlogger.seq_class')  # start the class logger
        if seqtext is None:
            seqtext = 'S1,1000,1000+t\nGreen,2000+t,5000+t\nMeasure,2000+t,2100+t'
        self.seq = []
        self.convert_text_to_seq(seqtext)  # this function creates the seq object, a list of list of strings
        self.timeres = float(timeres) * _ns  # old code was written assuming everything in ns, so fix that

        if pulseparams is None:
            self.pulseparams = _PULSE_PARAMS
        else:
            self.pulseparams = pulseparams
        if connectiondict is None:
            self.connectiondict = _CONN_DICT
        else:
            self.connectiondict = connectiondict
        self.delay = delay
        #
        self.num_of_channels = 0
        self.num_of_wait_events = 0
        self.channels = []
        self.channel_sampletimes = []
        self.seq_channel_indices = []
        self.wait_events = []  # handling waiting events separately since we simply turn everything off,
        # latest_sequence_event is the last time that a channel is turned off
        self.latest_sequence_event = 0
        self.first_sequence_event = 0

        # init the arrays
        self.wavedata = None
        self.c1markerdata = None
        self.c2markerdata = None

    def set_first_sequence_event(self):
        if self.num_of_channels > 1:
            temp_channels = []
            for channel in self.channels:
                channel.set_first_channel_event()
                if channel.num_of_events > 0:
                    temp_channels.append(channel)
            if len(temp_channels) > 0:
                self.first_sequence_event = sorted(temp_channels, key=lambda x: x.first_channel_event)[
                    0].first_channel_event
            else:
                self.first_sequence_event = 0
        if self.num_of_wait_events > 0:
            if float(self.wait_events[0]) < self.first_sequence_event:
                self.first_sequence_event = float(self.wait_events[0])

    def set_latest_sequence_event(self):
        self.latest_sequence_event = 0
        for i in range(self.num_of_channels):
            if self.channels[i].latest_channel_event > self.latest_sequence_event:
                self.latest_sequence_event = self.channels[i].latest_channel_event
        if self.num_of_wait_events > 0:
            if float(self.wait_events[-1]) > self.latest_sequence_event:
                self.latest_sequence_event = float(self.wait_events[-1])

    def add_channel(self, ch_type):
        """Adds a channel of specified channel type, but does not yet add the events data"""
        self.num_of_channels += 1
        if self.num_of_channels != 1:
            channel = Channel(ch_type=ch_type, delay=self.delay, pulse_params=self.pulseparams,
                              connection_dict=self.connectiondict, sampletime=self.timeres, event_channel_idx=
                              self.channels[-1].event_channel_index + 1)
        else:
            channel = Channel(ch_type=ch_type, delay=self.delay, pulse_params=self.pulseparams,
                              sampletime=self.timeres, connection_dict=self.connectiondict, event_channel_idx=0)
        self.channels.append(channel)
        self.channel_sampletimes.append(self.timeres)
        self.seq_channel_indices.append(channel.event_channel_index)
        self.set_latest_sequence_event()
        self.set_first_sequence_event()

    def delete_channel(self, index):
        """deletes the channel object"""
        if self.num_of_channels > 0:
            self.channels.pop(index)
            self.num_of_channels -= 1
            self.seq_channel_indices.pop(index)
            self.set_latest_sequence_event()
            self.set_first_sequence_event()
            return True
        else:
            return False

    def insert_channel_events(self, newchan: Channel):
        """This method inserts new events from a channel object newchan into the channel of the same type"""
        for (id, chan) in enumerate(self.channels):  # stepping through the channnels
            if chan.ch_type == newchan.ch_type:
                events = newchan.event_train   # get all the events in the newchan
                chan.event_train.extend(events)   # extend the channel with these events
                chan.event_start_times.extend(newchan.event_start_times)  # etend the start times

                chan.event_stop_times.extend(newchan.event_stop_times)   # extedn the stop times
                chan.num_of_events += len(events)     # update the number of events
                chan.event_channel_index += len(events)   # update the event index
                chan.set_first_channel_event()   # keep track of the new first channel event
                chan.set_latest_channel_event()  # and the last channel event
        # now we check all the other channels to see if we need to change any of their start/stop times
        self.adjust_channel_times(chantype=newchan.ch_type)
        self.set_first_sequence_event()
        self.set_latest_sequence_event()

    def adjust_channel_times(self, chantype='a1'):
        """this is a critical method that adjusts channel times for all other channels besides the one specified.
        THis is often needed when we either increment times in a given channel that would then end up conflicting
        with other channels start/stop times; or when we add new events into a channel
        :param chantype: string that gives the channel type that will not be adjusted """
        # first figure out which channel we are being asked to ignore
        insertchan = self.channels[0]
        for (id, chan) in enumerate(self.channels):
            if chan.ch_type == chantype:
                insertchan = chan
        # here we get all the start and stop times that we need from that channel
        earliest_start_time = insertchan.first_channel_event
        latest_stop_time = insertchan.latest_channel_event
        latest_start_time = np.amax(np.array(insertchan.event_start_times, dtype=np.float32))
        push_time = float(latest_start_time - earliest_start_time)
        for (id, chan) in enumerate(self.channels):
            if chan.ch_type != insertchan.ch_type:
                for idx, evt in enumerate(chan.event_train):
                    temp1 = evt.start_increment
                    temp2 = evt.stop_increment
                    if (evt.start > earliest_start_time) and (evt.start < latest_stop_time):
                        evt.start_increment = 1
                        evt.stop_increment = 1
                        evt.increment(dt=push_time)
                    evt.start_increment = temp1
                    evt.stop_increment = temp2
                    chan.event_start_times[idx] = evt.start
                    chan.event_stop_times[idx] = evt.stop
                chan.set_first_channel_event()
                chan.set_latest_channel_event()

    def find_start_stop_increment_times(self, pulse):
        """This method finds the start, stop and increment factors"""
        start, stop, start_increment, stop_increment = (0.0, 0.0, 0.0, 0.0)
        if '+' in pulse[1]:
            t1, t2 = pulse[1].split('+')  # '1000+2t' becomes '1000' and '2t'
            start = float(t1)
            if t2 == 't':
                start_increment = 1.0
            else:
                start_increment = float(t2[:-1])
        else:
            start = float(pulse[1])
        if '+' in pulse[2]:
            t1, t2 = pulse[2].split('+')
            stop = float(t1)
            if t2 == 't':
                stop_increment = 1.0
            else:
                stop_increment = float(t2[:-1])
        else:
            stop = float(pulse[2])
        return start, stop, start_increment, stop_increment

    def convert_text_to_seq(self, seqtext):
        """This method parses the sequence definition which is currently just a string, and converts
        it to a list of list of strings.  Eventually may include more sophisticated parsing techniques, e.g. using a
        lexer/parser library like PLY, ATL5"""
        # get a list of all the lines in the text
        all_lines = seqtext.split('\n')
        b_all_lines = all_lines[:]  # make a copy
        # now iterate over the copy, and create a list of a list of strings which specify the sequence
        for (idx, line) in list(enumerate(b_all_lines)):
            wfm = line.split(',')
            self.seq.append(wfm)
            # b_all_lines[idx:idx] = [wfm]
        # self.seq = self.seq[:-1]
        print('text box converted to', self.seq)

    def unpack_optional_params(self, seq_idx=0):
        '''get the optional params in the list of strings
        :param seq_idx: index in the list of strings to unpack
        '''
        ch_type = self.seq[seq_idx][0]  # type of channel
        opt_params = self.seq[seq_idx][3:]  # all the optional parameters
        # currently we support 4 parameters: pulsetype, num-events, amplitude_scale,fname
        amplitude_scale = 1.0
        num_events = 1
        fname = None
        pulsetype = ''
        if ch_type == _WAVE:  # if the ch_type is Wave, then we need several other params
            simple_ptypes = _PULSE_TYPES[0:-1]  # the simple pulsetypes e.g. Gauss, Sech etc
            # at a minimum this type must be present
            if len(opt_params) >= 1:
                try:
                    pulsetype = opt_params[0]
                    if pulsetype in simple_ptypes:  # check whether pulsetype is of 1st 3 types
                        # check if there are any other optional parameters
                        if len(opt_params) >= 2:
                            patt = r'(a[mp]?\s*\=\s*)(\d\.?\d*)'  # regex which allows amp = 1.0,a=1.0 etc
                            m = re.search(patt, str(opt_params[1]))
                            if m:
                                val = float(m.group(2))  # the match is returned in group 2
                                amplitude_scale = val if (0 <= val <= 1.0) else 1.0
                        if len(opt_params) >= 3:
                            patt = r'(n[ump]\s*=\s*)(\d{,4})[\.]?'  # regex which allows 1,n = 1,n=1 etc
                            m = re.search(patt, str(opt_params[2]))
                            if m:
                                val = int(m.group(2))  # the match is returned in group 2
                                num_events = val if (val > 1) else 1
                        else:
                            self.logger.warning(f"only 3 optional parameters supported for {pulsetype} channels")
                    elif pulsetype == _PULSE_TYPES[3]:  # this is for loading waveforms
                        # regex allows f = blah.txt, f = blah.csv ,fname = blah.txt etc
                        if len(opt_params) >= 2:
                            patt = r'(f[name]?\s*=\s*)(?P<file>\w+)\.(?P<ext>txt|csv)'
                            m = re.match(patt, opt_params[1])
                            fname = m.group('file') + '.' + m.group('ext') if m else None
                        else:
                            raise RuntimeWarning('Filename must be supplied else will use default')
                        # check if there are any other optional parameters
                        if len(opt_params) >= 3:
                            patt = r'(a[mp]?\s*\=\s*)(\d\.?\d*)'  # regex which allows amp = 1.0,a=1.0 etc
                            m = re.search(patt, str(opt_params[2]))
                            if m:
                                val = float(m.group(2))  # the match is returned in group 2
                                amplitude_scale = val if (0 <= val <= 1.0) else 1.0
                        if len(opt_params) >= 4:
                            patt = r'(n[ump]\s*=\s*)(\d{,4})[\.]?'  # regex which allows 1,n = 1,n=1 etc
                            m = re.search(patt, str(opt_params[3]))
                            if m:
                                val = int(m.group(2))  # the match is returned in group 2
                                num_events = val if (val > 1) else 1
                        else:
                            self.logger.warning(f"only 4 optional parameters supported for {pulsetype} channels")
                    else:
                        raise RuntimeError('Must specify type of pulse for Wave channels')
                except (RuntimeWarning, RuntimeError) as err:
                    self.logger.error('Runtime warning/error: {0}'.format(err))
                    sys.stderr.write('Runtime warning/error: {0}\n'.format(err))
        else:  # if channel type is marker, then only one other parameter is allowed, the number of pulses
            try:
                if opt_params is None:
                    num_events = 1
                elif len(opt_params) >= 1:
                    patt = r'(n\s*=\s*)(\d{,4})[\.]?'  # regex which allows 1 or n = 1
                    m = re.search(patt, str(opt_params[0]))
                    if opt_params[0] and m:
                        val = int(m.group(2))
                        num_events = val if (val > 1) else 1
                    else:
                        raise RuntimeError('only one opt param type n = D allowed for Marker types')
            except (RuntimeWarning, RuntimeError) as err:
                self.logger.error('Runtime warning/error: {0}'.format(err))
                sys.stderr.write('Runtime warning/error: {0}\n'.format(err))
        return pulsetype, amplitude_scale, num_events, fname

    def create_channels_from_seq(self, dt=0.0):
        """This method parses the sequence definition which is currently just a list of list of strings, and converts
        it to Channel objects.  Eventually may include more sophisticated parsing techniques, e.g. using a
        lexer/parser library like PLY, ATL5
        :param dt: increment for the start or stop times, will be multiplied by any increment factor specified in the string"""

        t_start = np.zeros(len(self.seq))
        t_stop = t_start.copy()
        start_inc = t_start.copy()
        stop_inc = t_start.copy()
        num_event_train = t_start.copy()
        ch_type = []
        self.set_first_sequence_event()
        self.set_latest_sequence_event()
        for i in range(len(self.seq)):
            # the first 3 in the list are mandatory
            ch_type.append(self.seq[i][0])
            t_start[i], t_stop[i], start_inc[i], stop_inc[i] = self.find_start_stop_increment_times(pulse=self.seq[i])
            # then we could have optional parameters
            ptype, ampfactor, nevents, fname = self.unpack_optional_params(seq_idx=i)
            # create the channel
            self.pulseparams['amplitude'] = self.pulseparams['amplitude'] * ampfactor
            self.pulseparams['num pulses'] = nevents
            num_event_train[i] = nevents
            self.add_channel(ch_type=ch_type[i])
            ch = self.channels[i]
            ch.add_event_train(time_on=t_start[i], time_off=t_stop[i], start_inc=start_inc[i],
                               stop_inc=stop_inc[i], pulse_type=ptype, events_in_train=nevents, dt=dt, fname=fname)
            self.adjust_channel_times(chantype=ch_type[i])   # if we need to adjust all the other channels after this
        self.set_first_sequence_event()
        self.set_latest_sequence_event()

    def create_sequence(self, dt=0.0):
        """Creates the data for the sequence.
        :param dt: Increment in time.
        """
        # get the AOM delay
        aomdelay = int((self.delay[0] + self.timeres / 2) / self.timeres)  # proper way of rounding delay[0]/timeres
        self.logger.info("AOM delay is found to be %d", aomdelay)
        # get the MW delay
        mwdelay = int((self.delay[1] + self.timeres / 2) // self.timeres)
        self.logger.info("MW delay is found to be %d", mwdelay)
        # create all the channels from the self.seq object
        self.create_channels_from_seq(dt=dt)
        # now we need to find the data length i.e. the largest stop time in the list of stop times
        maxend = np.int64(self.latest_sequence_event / self.timeres)
        # print("the max. event value is {}".format(self.maxend))
        # now we can init the arrays
        # dummydata = np.zeros(maxend, dtype=_MARKTYPE)
        c1m1 = np.zeros(maxend, dtype=_MARKTYPE)
        c1m2 = c1m1.copy()
        c2m1 = c1m1.copy()
        c2m2 = c1m1.copy()
        waveI = np.zeros(maxend, dtype=_IQTYPE)
        waveQ = waveI.copy()
        for (idx, channel) in enumerate(self.channels):
            if channel.ch_type == _WAVE:
                for (n, evt) in channel.event_train:
                    waveI[evt.t1_idx:evt.t2_idx] = evt.I_data
                    waveQ[evt.t1_idx:evt.t2_idx] = evt.Q_data
            elif channel.ch_type == _GREEN_AOM:
                for (n, evt) in channel.event_train:
                    c1m1[evt.t1_idx:evt.t2_idx] = evt.data
                c1m2 = np.roll(c1m2, -aomdelay)
            elif channel.ch_type == _MW_S2:
                for (n, evt) in channel.event_train:
                    c1m1[evt.t1_idx:evt.t2_idx] = evt.data
                c1m1 = np.roll(c1m1, -mwdelay)
            elif channel.ch_type == _MW_S1:
                for (n, evt) in channel.event_train:
                    c2m1[evt.t1_idx:evt.t2_idx] = evt.data
                c2m1 = np.roll(c2m1, -mwdelay)
                self.logger.warning('Value error: only MW switch connected is S2 using Ch1, M1, this channel will do nothing')
            elif channel.ch_type == _ADWIN_TRIG:
                for (n, evt) in channel.event_train:
                    c2m2[evt.t1_idx:evt.t2_idx] = evt.data
        self.c1markerdata = c1m1 + c1m2
        self.c2markerdata = c2m1 + c2m2
        # the wavedata will store the data for the I and Q channels in a 2D array
        self.wavedata = np.array((waveI, waveQ))


class SequenceList(object):
    def __init__(self, sequence, delay=None, scanparams=None, pulseparams=None, connectiondict=None, timeres=1):
        """This class creates a list of sequence objects that each have the waveforms for one step in the scanlist.
        Currently the only real new argument is
        :param scanparams : a dictionary that specifies the type, start, stepsize, number of steps
        so perhaps this entire class could be removed and just the function create_sequence_list could be put inside
        Sequence.
        However the main issue I encountered is that the function would have to create more instances of the
        sequence objects, especially for scans that change the pulsewidth or other aspects of the pulse like
        frequency etc. For now I will stay with this approach and later we can rewrite if needed.
        """
        if delay is None:
            delay = [0, 0]
        if scanparams is None:
            self.scanparams = {'type': 'amplitude', 'start': 0, 'stepsize': 10, 'steps': 10}
        else:
            self.scanparams = scanparams
        if pulseparams is None:
            self.pulseparams = {'amplitude': 0, 'pulsewidth': 20, 'SB freq': 0.00, 'IQ scale factor': 1.0,
                                'phase': 0.0, 'skew phase': 0.0, 'num pulses': 1}
        else:
            self.pulseparams = pulseparams
        if connectiondict is None:
            self.connectiondict = _CONN_DICT
        else:
            self.connectiondict = connectiondict
        self.scanlist = np.arange(self.scanparams['start'], self.scanparams['start'] + self.scanparams['stepsize'] *
                                  self.scanparams['steps'], self.scanparams['stepsize'])
        self.delay = delay
        self.pulseparams = pulseparams
        self.connectiondict = connectiondict
        self.timeres = timeres
        self.sequence = sequence
        self.sequencelist = []

    def create_sequence_list(self):
        # dt = float(self.scanparams['stepsize'])
        if self.scanparams['type'] == 'no scan':
            s = Sequence(self.sequence, delay=self.delay, pulseparams=self.pulseparams,
                         connectiondict=self.connectiondict, timeres=self.timeres)
            s.create_sequence(dt=0)
            self.sequencelist.append(s)
        else:
            for x in self.scanlist:
                if self.scanparams['type'] == 'time':
                    s = Sequence(self.sequence, delay=self.delay, pulseparams=self.pulseparams,
                                 connectiondict=self.connectiondict, timeres=self.timeres)
                    s.create_sequence(float(x))
                    self.sequencelist.append(s)
                elif self.scanparams['type'] == 'amplitude':
                    self.pulseparams['amplitude'] = float(x)
                    s = Sequence(self.sequence, delay=self.delay, pulseparams=self.pulseparams,
                                 connectiondict=self.connectiondict, timeres=self.timeres)
                    s.create_sequence(dt=0)
                    self.sequencelist.append(s)
                elif self.scanparams['type'] == 'SB freq':
                    self.pulseparams['SB freq'] = float(x)
                    s = Sequence(self.sequence, delay=self.delay, pulseparams=self.pulseparams,
                                 connectiondict=self.connectiondict, timeres=self.timeres)
                    s.create_sequence(dt=0)
                    self.sequencelist.append(s)
                elif self.scanparams['type'] == 'pulsewidth':
                    self.pulseparams['pulsewidth'] = float(x)
                    s = Sequence(self.sequence, delay=self.delay, pulseparams=self.pulseparams,
                                 connectiondict=self.connectiondict, timeres=self.timeres)
                    s.create_sequence(dt=0)
                    self.sequencelist.append(s)
                elif self.scanparams['type'] == 'number':
                    self.pulseparams['num pulses'] = int(x) + 1
                    s = Sequence(self.sequence, delay=self.delay, pulseparams=self.pulseparams,
                                 connectiondict=self.connectiondict, timeres=self.timeres)
                    s.create_sequence(dt=0)
                    self.sequencelist.append(s)
                elif self.scanparams['type'] == 'Carrier frequency':
                    s = Sequence(self.sequence, delay=self.delay, pulseparams=self.pulseparams,
                                 connectiondict=self.connectiondict, timeres=self.timeres)
                    s.create_sequence(dt=0)
                    self.sequencelist.append(s)
