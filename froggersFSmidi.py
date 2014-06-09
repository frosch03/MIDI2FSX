import os, sys
import struct

from string import join

import pygame
import pygame.midi
from pygame.locals import *

import pyuipc

default_midi_device = "Akai APC40"

def read_button_config():
    for line in apc40_button_layout:
        for chan in apc40_button_layout[line]:
            if (apc40_button_layout[line][chan] != None):
                (funct_data, state) = apc40_button_layout[line][chan]
                if funct_data[1] == None:
                    state = status_one_bit(funct_data[0]) 
                else:
                    state = status_one_of_many_bit(funct_data[0], funct_data[1])
                apc40_button_layout[line][chan] = (funct_data, state)

def init_button_config(board):
    for line in apc40_button_layout:
        for chan in apc40_button_layout[line]:
            if (apc40_button_layout[line][chan] != None):
                if (apc40_button_layout[line][chan][1] == True):
                    board.note_on(button[chan][line], channel=(int(chan)-1), velocity=color['green'])
                else:
                    board.note_on(button[chan][line], channel=(int(chan)-1), velocity=color['red'])

def change_ring_mode(board, _knob, _mode):
    knob = apc40_knob_layout[_knob[0]][_knob[1]]
    mode = led_ring_modes[_mode]

    # IMPROVEME: 0xB0 is only the first page
    board.write_short(0xB0, knob[1], mode)

def light_ring(board, _knob, value):
    knob = apc40_knob_layout[_knob[0]][_knob[1]]

    # IMPROVEME: 0xB0 is only the first page
    board.write_short(0xB0, knob[0], value)


def flush_button_config(board):
    for line in apc40_button_layout:
        for chan in apc40_button_layout[line]:
            if (apc40_button_layout[line][chan] != None):
                board.note_on(button[chan][line], channel=(int(chan)-1), velocity=color['off'])



def read_value(offset, lgt):
    dat = pyuipc.prepare_data([(offset, lgt)], True)
    return (pyuipc.read(dat)[0])
    
def read_double(offset):
    val = read_value(offset, 8)
    return struct.unpack('d', val)[0]

def read_int(offset):
    val = read_value(offset, 4)
    return struct.unpack('i', val)[0]

led_rings_to_update = {'rpm':   ((0x2408, 8), 
                                 (lambda x:  int(x*127)),
                                 ('L5')),
                       'ias':   ((0x02BC, 4), 
                                 (lambda x:  int((x/(200.0*128.0))*127)),
                                 ('L1')),
                       'fuelL': ((0x0B7C, 4), 
                                 (lambda x:  int(x/65535)),
                                 ('L3')),
                       'fuelR': ((0x0B94, 4), 
                                 (lambda x:  int(x/65535)),
                                 ('L4'))}

def update_knob(board):
    ul  = []
    fn  = []
    rng = []
    ks  = []
    fmts = {4:'i',
            8:'d'}

    for key in led_rings_to_update.keys():
        ul.append(led_rings_to_update[key][0])
        fn.append(led_rings_to_update[key][1])
        rng.append(led_rings_to_update[key][2])
        ks.append(key)

    pyuipc.prepare_data(ul, True)
    res = pyuipc.read(ul)

    # for i,r in enumerate(res): 
    #     print "(%d):%s => %d"%(i, 
    #                            ks[i], 
    #                            fn[i]( (struct.unpack(fmts[ul[i][1]], res[i])[0])) )

    for i,r in enumerate(res):
        light_ring(board, 
                   rng[i], 
                   fn[i]( (struct.unpack(fmts[ul[i][1]], res[i])[0]))  )




def status_one_bit(offset):
    lgt = 1
    dat = pyuipc.prepare_data([(offset, lgt)], True)
    val = pyuipc.read(dat)
    return (True if ord(val[0]) > 0 else False)

def status_one_of_many_bit(offset, bitNr):
    lgt = 1
    dat = pyuipc.prepare_data([(offset, lgt)], True)
    val_all = pyuipc.read(dat)
    val_bit = (ord(val_all[0]) & (1 << bitNr))
    return bool(val_bit)


def startup():
    pyuipc.open(pyuipc.SIM_FSX)

def shutdown():
    pyuipc.close()



def set_value(offset, typ, value):
    lgt = struct.calcsize(typ)
    dat = pyuipc.prepare_data([(offset, lgt)])
    pyuipc.write(dat, [struct.pack(typ, value)])

def set_fader(intuple, value):
    ((offset, lgt), fun) = intuple
    fmts = {1:   'c',
            2:   'h', 
            4:   'i',
            8:   'q',
            'd': 'd'}
    setval = fun(value)
    set_value(offset, fmts[lgt], setval)


def switch_one_bit(offset):
    lgt = 1
    dat = pyuipc.prepare_data([(offset, lgt)])
    val_ist = pyuipc.read(dat)
    val_sol = chr(not(ord(val_ist[0])))
    pyuipc.write(dat, [val_sol])


def decode_bcd(cs):
    return [(ord(x) >> 4,
             ord(x) & 0xF)
            for x in cs[::-1]]

def encode_bcd(vals):
    enc = map(lambda (x,y):chr((int(x) << 4) + 
                               (int(y) & 0xF))
              , vals)
    enc = enc[::-1]
    return (join(enc, sep=''))

def decode_freq(enc):
    freq_string = "1%i%i.%i%i%i" % (enc[0][0],
                                    enc[0][1],
                                    enc[1][0],
                                    enc[1][1],
                                    0 if (enc[1][1] == 0 or
                                          enc[1][1] == 5) else 5)
    return float(freq_string)

def encode_freq(dec):
    strg = "%7.3f"%dec
    result = [(strg[1], strg[2]),
              (strg[4], strg[5])]
    return result

def inc_com(freq):
    new = (freq + 0.025 if freq < 136.975 else 118.000)
    # Cope with the bug that \x00... can't be written...
    if new - float(int(new)) == 0:
        new = inc_com(new)
    return new

def dec_com(freq):
    new = (freq - 0.025 if freq > 118.000 else 136.975)
    # Cope with the bug that \x00... can't be written...
    if new - float(int(new)) == 0:
        new = dec_com(new)
    return new
    
def inc_fs_com1():
    lgt = 2
    dat = pyuipc.prepare_data([(0x311A, lgt)])
    val = pyuipc.read(dat)
    freq = decode_freq(decode_bcd(val[0]))
    new  = encode_bcd(encode_freq(inc_com(freq)))
    pyuipc.write(dat, [new])

def dec_fs_com1():
    lgt = 2
    dat = pyuipc.prepare_data([(0x311A, lgt)])
    val = pyuipc.read(dat)
    freq = decode_freq(decode_bcd(val[0]))
    new  = encode_bcd(encode_freq(dec_com(freq)))
    pyuipc.write(dat, [new])


pitot_heat = (0x029C, None)
alternator = (0x3101, None)
battery    = (0x3102, None)
avionics   = (0x3103, None)
fuel_pump  = (0x3104, None)
prop_deice = (0x2440, None)

vor1_morse = (0x3105, None)
vor2_morse = (0x3106, None)
adf_morse  = (0x3107, None)

beacon_light      = (0x0D0C, 1)
land_light        = (0x0D0C, 2)
taxi_light        = (0x0D0C, 3)
navi_light        = (0x0D0C, 0)
strobe_light      = (0x0D0C, 4)
instrument_light  = (0x0D0C, 5)
recognition_light = (0x0D0C, 6)
wing_light        = (0x0D0C, 7)
logo_light        = (0x0D0C, 8)
cabin_light       = (0x0D0C, 9)


def toggleBit(i, o):
    mask = 1 << o
    return(i ^ mask)

def switch_one_of_many_bit(offset, bitNr):
    lgt = 1
    dat = pyuipc.prepare_data([(offset, 1)])
    val_ist = pyuipc.read(dat)
    val_sol = chr(toggleBit(ord(val_ist[0]), bitNr))
    pyuipc.write(dat, [val_sol])


apc40_knob_layout = {'U': {'1': (0x30, 0x38),
                           '2': (0x31, 0x39),
                           '3': (0x32, 0x3A),
                           '4': (0x33, 0x3B),
                           '5': (0x34, 0x3C),
                           '6': (0x35, 0x3D),
                           '7': (0x36, 0x3E),
                           '8': (0x37, 0x3F)},
                     'L': {'1': (0x10, 0x18),
                           '2': (0x11, 0x19),
                           '3': (0x12, 0x1A),
                           '4': (0x13, 0x1B),
                           '5': (0x14, 0x1C),
                           '6': (0x15, 0x1D),
                           '7': (0x16, 0x1E),
                           '8': (0x17, 0x1F)}}

apc40_button_layout = {
    '1': { 
        '1': (fuel_pump,        False),
        '2': (beacon_light,     False),
        '3': (land_light,       False),
        '4': (taxi_light,       False),
        '5': (navi_light,       False),
        '6': (strobe_light,     False),
        '7': (pitot_heat,       False),
        '8': (instrument_light, False)},
    '2': { 
        '1': (alternator, False),
        '2': (battery,    False),
        '3': (avionics,   False),
        '4': None,
        '5': None,
        '5': None,
        '6': None,
        '7': None,
        '8': None},
    '3': {
        '1': None,
        '2': None,
        '3': None,
        '4': None,
        '5': None,
        '6': None,
        '7': None,
        '8': None},
    '4': {
        '1': None,
        '2': None,
        '3': None,
        '4': None,
        '5': None,
        '6': None,
        '7': None,
        '8': None},
    '5': {
        '1': None,
        '2': None,
        '3': None,
        '4': None,
        '5': None,
        '6': None,
        '7': None,
        '8': None}}


track_id = {'144': '1',
            '128': '1',
            '145': '2',
            '129': '2',
            '146': '3',
            '130': '3',
            '147': '4',
            '131': '4',
            '148': '5',
            '132': '5',
            '149': '6',
            '133': '6',
            '150': '7',
            '134': '7',
            '151': '8',
            '135': '8',
            '176': 'Fader',
            '177': 'Fader',
            '178': 'Fader',
            '179': 'Fader',
            '180': 'Fader',
            '181': 'Fader',
            '182': 'Fader',
            '183': 'Fader'}

key_id = {'53': '1',
          '54': '2',
          '55': '3',
          '56': '4',
          '57': '5',
          '82': 'SceneLaunch1',
          '83': 'SceneLaunch2',
          '84': 'SceneLaunch3',
          '85': 'SceneLaunch4',
          '86': 'SceneLaunch5',
          '47': 'CueLevel',
          '7' : 'Fader',
          '14': 'MasterFader',
          '15': 'CrossFader'}


apc40_fader_layout = {'176': {'7':  ((0x088E, 2),
                                     (lambda x: x*128)),
                              '14': ((0x0BDC, 4), 
                                     (lambda x:  16384 - ((x+1)*128))),
                              '15': None},
                      '177': {'7':  None},
                      '178': {'7':  ((0x0890, 2), 
                                     (lambda x: x*128))},
                      '179': {'7':  None},
                      '180': {'7':  None},
                      '181': {'7':  None},
                      '182': {'7':  None},
                      '183': {'7':  None}}

button = {'1': {'1':0x35,
                '2':0x36,
                '3':0x37, 
                '4':0x38, 
                '5':0x39, 
                'Record':   0x30,
                'Solo':     0x31,
                'Activate': 0x32,
                'TrackSelect': 0x33,
                'ClipStop':    0x34},
          '2': {'1':0x35,
                '2':0x36,
                '3':0x37, 
                '4':0x38, 
                '5':0x39, 
                'Record':   0x30,
                'Solo':     0x31,
                'Activate': 0x32,
                'TrackSelect': 0x33,
                'ClipStop':    0x34},
          '3': {'1':0x35,
                '2':0x36,
                '3':0x37, 
                '4':0x38, 
                '5':0x39, 
                'Record':   0x30,
                'Solo':     0x31,
                'Activate': 0x32,
                'TrackSelect': 0x33,
                'ClipStop':    0x34},
          '4': {'1':0x35,
                '2':0x36,
                '3':0x37, 
                '4':0x38, 
                '5':0x39, 
                'Record':   0x30,
                'Solo':     0x31,
                'Activate': 0x32,
                'TrackSelect': 0x33,
                'ClipStop':    0x34},
          '5': {'1':0x35,
                '2':0x36,
                '3':0x37, 
                '4':0x38, 
                '5':0x39, 
                'Record':   0x30,
                'Solo':     0x31,
                'Activate': 0x32,
                'TrackSelect': 0x33,
                'ClipStop':    0x34},
          '6': {'1':0x35,
                '2':0x36,
                '3':0x37, 
                '4':0x38, 
                '5':0x39, 
                'Record':   0x30,
                'Solo':     0x31,
                'Activate': 0x32,
                'TrackSelect': 0x33,
                'ClipStop':    0x34},
          '7': {'1':0x35,
                '2':0x36,
                '3':0x37, 
                '4':0x38, 
                '5':0x39, 
                'Record':   0x30,
                'Solo':     0x31,
                'Activate': 0x32,
                'TrackSelect': 0x33,
                'ClipStop':    0x34},
          '8': {'1':0x35,
                '2':0x36,
                '3':0x37, 
                '4':0x38, 
                '5':0x39, 
                'Record':   0x30,
                'Solo':     0x31,
                'Activate': 0x32,
                'TrackSelect': 0x33,
                'ClipStop':    0x34},
          'Master':0x50,
          'SceneLaunch1':0x52,
          'SceneLaunch2':0x53,
          'SceneLaunch3':0x54,
          'SceneLaunch4':0x55,
          'SceneLaunch5':0x56}


color = {'off':    0,
         'green':  1,
         'red':    3, 
         'orange': 5}


led_ring_modes = {'off':    0,
                  'single': 1,
                  'volume': 2,
                  'pan':    3}

def get_device_nr():
    in_result = None
    out_result = None
    for i in range( pygame.midi.get_count() ):
        r = pygame.midi.get_device_info(i)
        (interf, name, input, output, opened) = r

        if (name == default_midi_device):
            if input:
                in_result  = i
            if output:
                out_result = i        
    return(in_result, out_result)


def light_apc40_button(board, chan, line):
    note_nr = button[chan][line]

    (funct_data, state) = apc40_button_layout[line][chan]

    if (state != True):
        board.note_on(note_nr, channel=(int(chan)-1), velocity=color['green'])
        apc40_button_layout[line][chan] = (funct_data, True)
    else:
        board.note_on(note_nr, channel=(int(chan)-1), velocity=color['red'])
        apc40_button_layout[line][chan] = (funct_data, False)

def main():
    going = True
    error = False
    startup()

    pygame.init()
    pygame.fastevent.init()
    event_get  = pygame.fastevent.get
    event_post = pygame.fastevent.post

    pygame.midi.init()



    (input_id, output_id) = get_device_nr()

    if input_id == None: 
        print "Can't find input device \"%s\""% default_midi_device
        error = True
    if output_id == None:
        print "Can't find output device \"%s\""% default_midi_device
        error = True

    if error:
        pygame.midi.quit()
        going = False

    print ("Using %s for input (id: %s)" % (default_midi_device, input_id))
    i = pygame.midi.Input(input_id)

    print ("Using %s for output (id: %s)" % (default_midi_device, output_id))
    o = pygame.midi.Output(output_id)

    change_ring_mode(o, 'L2', 'off')
    change_ring_mode(o, 'L6', 'off')
    change_ring_mode(o, 'L7', 'off')
    change_ring_mode(o, 'L8', 'off')

    for ky in led_rings_to_update.keys():
        change_ring_mode (o, 
                          led_rings_to_update[ky][2],
                          'volume')


    read_button_config()
    init_button_config(o)

    pygame.display.set_mode((1,1))

    while going:
        events = event_get()
        update_knob(o)
        for e in events:
            if e.type in [QUIT]:
                going = False
            if e.type in [KEYDOWN]:
                if (e.scancode == 1):
                    going = False
                else:
                    print (e)
            if e.type in [pygame.midi.MIDIIN]:
                try:
                    cur_press = ""
                    cur_track = track_id[str(e.status)]
                    if e.status >= 128 and e.status <= 135: cur_press = "UP" 
                    if e.status >= 144 and e.status <= 151: cur_press = "DOWN" 
                    cur_key = key_id[str(e.data1)]

                    if cur_press == "DOWN":
                        press_apc40_button(apc40_button_layout[cur_key][cur_track])
                    
                    if cur_press == "UP":
                        light_apc40_button(o, cur_track, cur_key)

                    if (cur_track == 'Fader') :
                        if cur_key == 'CueLevel':
                            if e.data2 < 64: inc_fs_com1()
                            else:            dec_fs_com1()
                        if cur_key == 'Fader' or cur_key == 'MasterFader' : 
                            print (e.data2 * 128)
                            set_fader(apc40_fader_layout[str(e.status)][str(e.data1)], e.data2)

                except:
                    print (e)

        if i.poll():
            midi_events = i.read(10)
            midi_evs  = pygame.midi.midis2events(midi_events, i.device_id)

            for m_e in midi_evs:
                event_post( m_e )

    for ky in led_rings_to_update.keys():
        change_ring_mode (o, 
                          led_rings_to_update[ky][2],
                          'off')


    flush_button_config(o)
    shutdown()
    del i
    del o
    pygame.midi.quit()



def press_apc40_button(intuple):
    try:
        funct_data = intuple[0]
        if funct_data[1] == None:
            switch_one_bit(funct_data[0]) 
        else:
            switch_one_of_many_bit(funct_data[0], funct_data[1])
    except:
        pass

if __name__ == '__main__':
    main()
