#!/usr/bin/env python2
# -*- coding: utf-8 -*-

description_text = """

"""

import sys, io, os, datetime, time, random
import re, codecs, locale, pwd
import socket, urllib2, sys, traceback
from urllib2   import urlopen
from stat import *
from xml.etree import cElementTree as ET
from threading import Thread
try:
    from subprocess32 import *
except:
    from subprocess import *

class FunctionConfig:

    def __init__(self):
        self.name = 'radioFunctions.py'
        self.major = 0
        self.minor = 3
        self.patch = 0
        self.beta = True

        self.log_queue = None
        self.stderr_write = None

        self.__CONFIG_SECTIONS__ = { 1: u'Radio Channels'}
        self.__BOOL_VARS__ = []
        self.__INT_VARS__ = ['radio_cardtype']
        self.__STR_VARS__ = ['audio_card', 'audio_mixer']
        self.__NONE_STR_VARS__ = ['radio_device', 'radio_out', 'video_device', 'myth_backend','source_switch' , 'source','source_mixer']
        self.functioncalls = {u'play_radio'              :u'PlayRadio',
                                         u'stop_radio'              :u'StopRadio',
                                         u'start_stop_radio'  :u'ToggleStartStop',
                                         u'ch+'                            :u'ChannelUp',
                                         u'ch-'                            :u'ChannelDown',
                                         u'v+'                              :u'VolumeUp',
                                         u'v-'                              :u'VolumeDown',
                                         u'mute'                          :u'Mute',
                                         u'create_mythfmmenu':u'CreateMythfmMenu'}
        self.opt_dict = {}

        self.myth_menu_file = 'fmmenu.xml'
        self.active_channel = 1
        self.new_channel = 0
        self.radio_pid = None
        self.play_pcm = None
        self.mixer = None
        self.audio_out = None

        self.mutetext = {}
        self.mutetext[0] = 'Unmuting'
        self.mutetext[1] = 'Muting'

        self.chan_cnt = 0
        self.channels = {}
        self.frequencies = {}

        self.disable_alsa = False
        self.disable_radio = False
        try:
            global alsaaudio
            import alsaaudio
            try:
                x = alsaaudio.pcms()
                self.alsa_version = '0.8'

            except:
                self.alsa_version = '0.7'

        except:
            print 'You need to install the pyalsaaudio module\n'
            print 'Alsa (and radio) support will be disabled\n'
            self.disable_alsa = True

        self.alsa_cards = {}
        self.alsa_names = {}
        self.get_alsa()

    # end Init()

    def version(self, as_string = False):
        if as_string and self.beta:
            return u'%s Version: %s.%s.%s-beta' % (self.name, self.major, self.minor, self.patch)

        if as_string and not self.beta:
            return u'%s Version: %s.%s.%s' % (self.name, self.major, self.minor, self.patch)

        else:
            return (self.name, self.major, self.minor, self.patch, self.beta)

    # end version()

    def init_plugin(self, ivtv_dir, plugin_list):
        self.ivtv_dir = ivtv_dir

        # Initialising radio and audio
        self.dev_types = {}
        self.dev_types[0] = 'ivtv radio device'
        self.dev_types[1] = 'radio with alsa device'
        self.dev_types[2] = 'radio cabled to an audio card'
        self.opt_dict['myth_backend'] = None
        self.opt_dict['radio_cardtype'] = -1
        self.opt_dict['radio_device']  = None
        self.opt_dict['radio_out'] = None
        self.opt_dict['source_switch'] = None
        self.opt_dict['source'] = None
        self.opt_dict['source_mixer'] = None

        self.check_dependencies()
        # Detecting radio and audio defaults
        self.select_card = u'You have to set audio-card to where the tv-card is cabled to: ['
        if self.disable_alsa:
            self.select_card = self.select_card + u']'

        else:
            for a in alsaaudio.cards():
                self.select_card += u'%s, ' % a

            self.select_card = self.select_card[0: -2] + u']'

        self.detect_radiodevice()
        if len(self.radio_devs) > 0:
            for card in self.radio_devs:
                if card['radio_cardtype'] == 0:
                    # There is a ivtv-radiocard
                    self.opt_dict['radio_cardtype'] = card['radio_cardtype']
                    self.opt_dict['radio_device']  = card['radio_device']
                    self.opt_dict['radio_out'] = card['radio_out']
                    self.opt_dict['video_device'] =card['video_device']

            else:
                #We take the first
                self.opt_dict['radio_cardtype'] = self.radio_devs[0]['radio_cardtype']
                self.opt_dict['radio_device']  = self.radio_devs[0]['radio_device']
                self.opt_dict['radio_out'] = self.radio_devs[0]['radio_out']
                self.opt_dict['video_device'] =self.radio_devs[0]['video_device']

        self.opt_dict['audio_card'] = alsaaudio.cards()[0]
        for m in ('Front', 'Master', 'PCM'):
            if m in alsaaudio.mixers(0):
                self.opt_dict['audio_mixer'] = m
                break

        else:
            self.opt_dict['audio_mixer'] = alsaaudio.mixers(0)[0]

    # end init_plugin()

    def init_parser(self, parser):

        parser.add_argument('--card-type', type = str, default = None, dest = 'radio_cardtype',
                        metavar = '<device>',
                        help = 'type of radio-device/ (%s)\n' % self.opt_dict['radio_cardtype'] +
                                    '   0 = ivtv (with /dev/video24 radio-out)\n' +
                                    '   1 = with corresponding alsa device\n' +
                                    '   2 = cabled to an audiocard\n' +
                                    '  -1 = No radiocard' )

        parser.add_argument('--radio-device', type = str, default = None, dest = 'radio_device',
                        metavar = '<device>',
                        help = 'name of the radio-device in /dev/ (%s)\n' % self.opt_dict['radio_device'] )

        parser.add_argument('--radio-out', type = str, default = None, dest = 'radio_out',
                        metavar = '<device>',
                        help = 'name of the audio-out-device in /dev/ or\n' +
                                    'the alsa device (%s)' % self.opt_dict['radio_out'])

        parser.add_argument('--video-device', type = str, default = None, dest = 'video_device',
                        metavar = '<device>',
                        help = 'name of the corresponding video-device in /dev/\n(%s)' % self.opt_dict['video_device'] )

        parser.add_argument('--myth-backend', type = str, default = None, dest = 'myth_backend',
                        metavar = '<hostname>',
                        help = 'backend dns hostname. (%s)\nSet to \'None\' string to disable checking.' % self.opt_dict['myth_backend'])

        parser.add_argument('--audio-card', type = str, default = None, dest = 'audio_card',
                        metavar = '<cardname>',
                        help = 'The audiocard name to play the radio. (%s)\n' % self.opt_dict['audio_card'])

        parser.add_argument('--audio-mixer', type = str, default = None, dest = 'audio_mixer',
                        metavar = '<mixername>',
                        help = 'The mixer name. (%s)\n' % self.opt_dict['audio_mixer'])

        parser.add_argument('--list-alsa-cards', action = 'store_true', default = False, dest = 'list_alsa',
                        help = 'Give a list of the alsa-audio cards on this system')

        parser.add_argument('--list-mixers', action = 'store_true', default = False, dest = 'list_mixers',
                        help = 'Give a list of the available mixer-controls for the given card')

        if self.alsa_version == '0.8':
            parser.add_argument('--list-pcms', action = 'store_true', default = False, dest = 'list_pcms',
                            help = "Give a list of the available PCM's")

        parser.add_argument('--create-menu', action = 'store_true', default = False, dest = 'create_menu',
                        help = 'create a Radiomenu file %s in %s\n' % (self.myth_menu_file, self.ivtv_dir) +
                                    'with the defined channels to be used in MythTV.')

        return parser

    # end init_parser()

    def commandline_queries(self, args, opt_dict):

        if args.list_alsa:
            print 'The available alsa audio-cards are:'
            for c in alsaaudio.cards():
                print '    %s' % c

            return(0)

        if args.list_mixers:
            if args.audio_card != None and args.audio_card in alsaaudio.cards():
                self.opt_dict['audio_card'] = args.audio_card

            cardid = RadioFunctions().get_cardid(self.opt_dict['audio_card'])
            print 'The available mixer controls for audio-card: %s are:' % self.opt_dict['audio_card']
            for m in alsaaudio.mixers(cardid):
                print '    %s' % m

            return(0)

        if args.list_pcms:
            print "The available playback PCM's are:"
            for m in alsaaudio.pcms(alsaaudio.PCM_PLAYBACK):
                print '    %s' % m

            print "The available capture PCM's are:"
            for m in alsaaudio.pcms(alsaaudio.PCM_CAPTURE):
                print '    %s' % m

            return(0)

        if args.create_menu:
            self.opt_dict['fifo_file'] = opt_dict['fifo_file']

            RadioFunctions().create_fm_menu_file()
            return(0)

    # end commandline_queries()

    def validate_config_line(self, type, line):
        # Read the channel stuff
        if type == 1:
            try:
                # Strip the name from the frequency
                a = line.split('=',1)
                if len(a) != 2:
                    log('Ignoring incomplete Channel line in config file %s: %r\n' % (file, line))
                    return

                self.chan_cnt += 1
                self.frequencies[float(a[0].strip())] = self.chan_cnt
                self.channels[self.chan_cnt] = {}
                self.channels[self.chan_cnt]['frequency'] = float(a[0].strip())
                self.channels[self.chan_cnt]['title'] = unicode(a[1].strip())
                if self.channels[self.chan_cnt]['title'] == '':
                    self.channels[self.chan_cnt]['title'] = u'Frequency %s' % a[0].strip()

            except Exception:
                self.chan_cnt -= 1
                log('Invalid Channel line in config file %s: %r\n' % (file, line))

    # validate_config_line()

    def validate_options(self, args):

        def is_video_device(path):
            if path == None or path.lower() == 'none':
                return None

            if (not os.access(path, os.F_OK and os.R_OK)):
                return False

            if ((os.major(os.stat(path).st_rdev)) != 81):
                return False

            return path

        if args.myth_backend != None:
            self.opt_dict['myth_backend'] = args.myth_backend

        if self.opt_dict['myth_backend'] == None:
            if RadioFunctions().query_backend(socket.gethostname()) != -2:
                self.opt_dict['myth_backend'] = socket.gethostname()

        elif self.opt_dict['myth_backend'].lower().strip() == 'none':
            self.opt_dict['myth_backend'] = None

        if self.opt_dict['myth_backend'] != None and RadioFunctions().query_backend(self.opt_dict['myth_backend']) == -2:
            log('The MythTV backend %s is not responding!\n' % self.opt_dict['myth_backend'],1)
            log('Run with --myth-backend None to disable checking!\n', 0)

        if args.radio_cardtype != None:
            self.opt_dict['radio_cardtype'] = args.radio_cardtype

        if self.opt_dict['radio_cardtype'] != None and 0 <= self.opt_dict['radio_cardtype'] <= 2:
            if args.radio_device != None:
                x = is_video_device(args.radio_device)
                if x != False:
                    self.opt_dict['radio_device'] = x

            x = is_video_device(self.opt_dict['radio_device'])
            if x == False:
                log('%s is not readable or not a valid radio device. Disabling radio\n' % self.opt_dict['radio_device'])
                self.opt_dict['radio_cardtype'] = None
                self.opt_dict['radio_device'] = None
                self.opt_dict['video_device'] = None
                self.opt_dict['radio_out'] = None

            else:
                self.opt_dict['radio_device'] = x
                udevpath =  RadioFunctions().query_udev_path( self.opt_dict['radio_device'], 'video4linux')
                autodetect_card = None
                for card in self.radio_devs:
                    if card['udevpath'] == udevpath:
                        autodetect_card = card
                        self.opt_dict['radio_cardtype'] = card['radio_cardtype']
                        break

                else:
                    log('%s is not a valid radio device. Disabling radio\n' % self.opt_dict['radio_device'])
                    self.opt_dict['radio_cardtype'] = None
                    self.opt_dict['radio_device'] = None
                    self.opt_dict['video_device'] = None
                    self.opt_dict['radio_out'] = None

        else:
            self.opt_dict['radio_cardtype'] = None
            self.opt_dict['radio_device'] = None
            self.opt_dict['video_device'] = None
            self.opt_dict['radio_out'] = None

        if self.opt_dict['radio_cardtype'] != None:
            if args.video_device != None:
                self.opt_dict['video_device'] = args.video_device

            udevpath =  RadioFunctions().query_udev_path( self.opt_dict['video_device'], 'video4linux')
            if autodetect_card['udevpath'] != udevpath:
                log('%s is not the corresponding video device. Setting to %s\n' % (self.opt_dict['video_device'], autodetect_card['video_device']))
                self.opt_dict['video_device'] = autodetect_card['video_device']

            if args.radio_out != None:
                self.opt_dict['radio_out'] = args.radio_out

            if self.opt_dict['radio_cardtype'] == 0:
                udevpath =  RadioFunctions().query_udev_path( self.opt_dict['radio_out'], 'video4linux')
                if autodetect_card['udevpath'] != udevpath:
                    log('%s is not the corresponding radio-out device. Setting to %s\n' % (self.opt_dict['radio_out'], autodetect_card['radio_out']))
                    self.opt_dict['radio_out'] = autodetect_card['radio_out']

            elif self.opt_dict['radio_cardtype'] == 1:
                if autodetect_card['radio_out'] != self.opt_dict['radio_out']:
                    log('%s is not the corresponding alsa device. Setting to %s\n' % (self.opt_dict['radio_out'], autodetect_card['radio_out']))
                    self.opt_dict['radio_out'] = autodetect_card['radio_out']

            elif self.opt_dict['radio_cardtype'] == 2 and self.opt_dict['radio_out'] == self.select_card:
                log(self.select_card + u'\n')

        else:
            self.opt_dict['radio_cardtype'] = -1
            self.opt_dict['radio_device']  = None
            self.opt_dict['radio_out'] = None
            self.opt_dict['video_device'] = None

        if args.audio_card != None:
            if args.audio_card in RadioFunctions().get_alsa_cards():
                self.opt_dict['audio_card'] = args.audio_card

            else:
                log('%s is not a recognized audiocard\n' % args.audio_card, 1)

        if not self.opt_dict['audio_card'] in RadioFunctions().get_alsa_cards():
            log('%s is not a recognized audiocard\n' % self.opt_dict['audio_card'], 1)
            self.opt_dict['audio_card'] = RadioFunctions().get_alsa_cards(0)

        cardid = RadioFunctions().get_cardid(self.opt_dict['audio_card'])

        if args.audio_mixer != None:
            if args.audio_mixer in RadioFunctions().get_alsa_mixers(cardid):
                self.opt_dict['audio_mixer'] = args.audio_mixer

            else:
                log('%s is not a recognized audiomixer\n' % args.audio_mixer, 1)

        if not self.opt_dict['audio_mixer'] in RadioFunctions().get_alsa_mixers(cardid):
            log('%s is not a recognized audiomixer\n' % self.opt_dict['audio_mixer'], 1)
            self.opt_dict['audio_card'] = RadioFunctions().get_alsa_mixers(cardid, 0)

    # end validate_options()

    def final_validation(self):

        if self.opt_dict['radio_out'] == self.select_card:
            self.opt_dict['radio_out'] = None

        if len(self.channels) == 0:
            # There are no channels so looking for an old ~\.ivtv\radioFrequencies file
            if not self.read_radioFrequencies_File():

                # We scan for frequencies
                self.freq_list = RadioFunctions().detect_channels(config.opt_dict['radio_device'])
                if len(self.freq_list) == 0:
                    self.disable_radio = True
                    log('No Frequencies defined or detected! Disabling radiofunctionality.\n')

                else:
                    ch_num = 0
                    for freq in self.freq_list:
                        ch_num += 1
                        self.frequencies[freq] = ch_num
                        self.channels[ch_num] = {}
                        self.channels[ch_num]['frequency'] = freq
                        self.channels[ch_num]['title'] = 'Channel %s' % ch_num

        if self.opt_dict['radio_cardtype'] != None and 0 <= self.opt_dict['radio_cardtype'] <= 2:
            if not self.set_mixer():
                log('Error setting the mixer\n')
                return(1)

    # final_validation()

    def write_opts_to_log(self):
        """
        Save the the used options to the logfile
        """
        log(u'',1, 2)
        log(u'Starting radioFunctions\n',1, 2)
        log(u'The Netherlands (%s)\n' % self.version(True), 1, 2)
        log(u'radio_cardtype = %s\n' % self.opt_dict['radio_cardtype'], 1, 2)
        log(u'radio_device = %s\n' % self.opt_dict['radio_device'], 1, 2)
        log(u'radio_out = %s\n' % self.opt_dict['radio_out'], 1, 2)
        log(u'video_device = %s\n' % self.opt_dict['video_device'], 1, 2)
        log(u'myth_backend = %s\n' % self.opt_dict['myth_backend'], 1, 2)
        log(u'audio_card = %s\n' % self.opt_dict['audio_card'], 1, 2)
        log(u'audio_mixer = %s\n' % self.opt_dict['audio_mixer'], 1, 2)
        log(u'source_switch = %s\n' % self.opt_dict['source_switch'], 1, 2)
        log(u'source = %s\n' % self.opt_dict['source'], 1, 2)
        #~ log(u'source_mixer = %s\n' % self.opt_dict['source_mixer'], 1, 2)
        log(u'',1, 2)

    # end write_opts_to_log()

    def write_opts_to_config(self, config_file):

        config_file.write(u'\n')
        config_file.write(u'# The Options for the radioFunctions Plugin\n')
        config_file.write(u'# radio_cardtype can be any of four values \n')
        config_file.write(u'# 0 = ivtv (with /dev/video24 as radio-out)\n')
        config_file.write(u'# 1 = with corresponding alsa device as radio-out\n')
        config_file.write(u'# 2 = cabled to the audiocard set in audio_card\n')
        config_file.write(u'#     You also have to set "source_switch" and "source"\n')
        config_file.write(u'#     to the source select mixer and its value\n')
        config_file.write(u'# -1 = No radiocard\n')
        config_file.write(u'# All but the audiocard for type 2 will be autodetected\n')
        config_file.write(u'# It will default to the first detected ivtv-card or else any other.\n')
        config_file.write(u'radio_cardtype = %s\n' % self.opt_dict['radio_cardtype'])
        config_file.write(u'radio_device = %s\n' % self.opt_dict['radio_device'])
        config_file.write(u'radio_out = %s\n' % self.opt_dict['radio_out'])
        config_file.write(u'video_device = %s\n' % self.opt_dict['video_device'])
        config_file.write(u'myth_backend = %s\n' % self.opt_dict['myth_backend'])
        config_file.write(u'audio_card = %s\n' % self.opt_dict['audio_card'])
        config_file.write(u'audio_mixer = %s\n' % self.opt_dict['audio_mixer'])
        config_file.write(u'source_switch = %s\n' % self.opt_dict['source_switch'])
        config_file.write(u'source = %s\n' % self.opt_dict['source'])
        #~ config_file.write(u'source_mixer = %s\n' % self.opt_dict['source_mixer'])
        #config_file.write(u' = %s\n' % self.opt_dict[''])
        config_file.write(u'\n')

    # end write_opts_to_config()

    def write_config_section(self, config_file, sectionid, copy_old):
        if not sectionid in self.__CONFIG_SECTIONS__.keys():
            return

        if sectionid == 1:
            config_file.write(u'# These are the channels to use. You can disable a channel by placing\n')
            config_file.write(u'# a \'#\' in front. You can change the names to suit your own preferences.\n')
            config_file.write(u'# Place them in the order you want them numbered.\n')
            config_file.write(u'\n')
            config_file.write(u'[%s]\n' % self.__CONFIG_SECTIONS__[sectionid])

            if self.opt_dict['radio_device'] == None:
                log('You need an accesible radio-device to configure\n')
                copy_old = True

            if copy_old != False:
                # just copy over the channels section
                fo = io.open(self.args.config_file + '.old', 'rb')
                if fo == None or not self.check_encoding(fo):
                    # We cannot read the old config, so we create a new one
                    log('Error Opening the old config. Trying for an old radioFrequencies file.\n')
                    x = self.read_radioFrequencies_File()
                    if x == False:
                        log('Error Opening an old radioFrequencies file. Creating a new Channellist.\n')

                    copy_old = False

                else:
                    copy_old = True

                if copy_old != False:
                    fo.seek(0,0)
                    type = 0
                    if copy_old == None:
                        # it's an old type config without sections
                        type = 1

                    for byteline in fo.readlines():
                        line = self.get_line(fo, byteline, None)
                        try:
                            if line == '# encoding: utf-8' or line == False:
                                continue

                            # Look for section headers
                            config_title = re.search('\[(.*?)\]', line)
                            if config_title != None and (config_title.group(1) in self.__CONFIG_SECTIONS__.values()):
                                for i, v in self.__CONFIG_SECTIONS__.items():
                                    if v == config_title.group(1):
                                        type = i
                                        continue
                                continue

                            if type == 1:
                                # We just copy everything in this section
                                config_file.write(line + u'\n')
                        except:
                            log('Error reading old config\n')
                            log(traceback.format_exc())
                            continue

                    fo.close()
                    f.close()
                    return True

            if not copy_old:
                self.freq_list = rfcalls().detect_channels(config.opt_dict['radio_device'])
                ch_num = 0
                for c in rfconf.channels.itervalues():
                    ch_num += 1
                    if c['frequency'] in self.freq_list:
                        config_file.write(u'%s = %s\n' % (c['frequency'], c['title']))
                        self.freq_list.remove(c['frequency'])

                    else:
                        for i in (0.1, -0.1, 0.2, -0.2):
                            if c['frequency'] + i in self.freq_list:
                                config_file.write(u'%s = %s\n' % (c['frequency'] + i, c['title']))
                                self.freq_list.remove(c['frequency'] + i)
                                break

                        else:
                            config_file.write(u'# Not detected frequency: %s = %s\n' % (c['frequency'], c['title']))

                for freq in self.freq_list:
                    ch_num += 1
                    config_file.write(u'%s = Channel %s\n' % (freq, ch_num))


    # end write_config_section()

    def add_command_help(self, config_file):
        config_file.write(u'# In the radioFunctions plugin available commands are:.\n')
        config_file.write(u'#   PlayRadio, StopRadio, ToggleStartStop, ChannelUp, ChannelDown, \n')
        config_file.write(u'#   VolumeUp, VolumeDown, Mute, CreateMythfmMenu \n')
        config_file.write(u'\n')

    # end add_command_help()

    def read_radioFrequencies_File(self):
        """Check for an old RadioFrequencies file."""

        if not os.access(self.ivtv_dir +  '/radioFrequencies', os.F_OK and os.R_OK) :
            return False

        f = io.open(self.ivtv_dir +  '/radioFrequencies', 'rb')
        if f == None:
            return False

        f.seek(0,0)
        ch_num = 0
        for byteline in f.readlines():
            try:
                line = byteline.decode('utf-8')
                if len(line) == 0 or line[0:1] == '#':
                    continue

                # Read the channel stuff
                try:
                    # Strip the name from the frequency
                    a = re.split(';',line)
                    if len(a) != 2:
                        continue

                    ch_num += 1
                    self.frequencies[float(a[1].strip())] = ch_num
                    self.channels[ch_num] = {}
                    self.channels[ch_num]['title'] = a[0].strip()
                    self.channels[ch_num]['frequency'] = float(a[1].strip())
                    if self.channels[ch_num]['title'] == '':
                        self.channels[ch_num]['title'] = u'Frequency %s' % a[1].strip()

                except Exception:
                    log('Invalid line in config file %s: %r\n' % (self.ivtv_dir +  '/radioFrequencies', line))
                    continue

            except Exception as e:
                log(u'Error reading Config\n')
                log(traceback.format_exc())
                continue

        f.close()

        if len(self.channels) == 0:
            return False

        return True

    # end read_radioFrequencies_File()

    def retrieve_value(self, name, default):
        # Retrieve old values
        if os.access('%s/%s' % (self.ivtv_dir, name), os.F_OK):
            f = io.open('%s/%s' % (self.ivtv_dir, name), 'rb')
            value = int(re.sub('\n','', f.readline()).strip())
            f.close()
            return value

        return default

    # end retrieve_value()

    def save_value(self, name, value):
        # save a value for later
        if os.access('%s/%s' % (self.ivtv_dir, name), os.F_OK) and not os.access('%s/%s' % (self.ivtv_dir, name), os.W_OK):
            log('Can not save %s/%s. Check access rights\n' % (self.ivtv_dir, name) )

        try:
            f = io.open('%s/%s' % (self.ivtv_dir, name), 'wb')
            f.write('%s\n' % value)
            f.close()

        except:
            log('Can not save %s/%s. Check access rights\n' % (self.ivtv_dir, name) )

    # end save_value()

    def check_dependencies(self):

        def check_path(name, use_sudo = False):
            if use_sudo:
                try:
                    path = check_output(['sudo', 'which', name], stderr = None)
                    return re.sub('\n', '',path)

                except:
                    log('%s not Found!\n' % (name))
                    return None

            else:
                try:
                    path = check_output(['which', name], stderr = None)
                    return re.sub('\n', '',path)

                except:
                    log('%s not Found!\n' % (name))
                    return None

        self.active_channel = int(self.retrieve_value('LastChannel', 1))

        self.udevadm = check_path("udevadm")
        self.ivtv_radio = check_path("ivtv-radio")
        self.ivtv_tune = check_path("ivtv-tune")
        self.v4l2_ctl = check_path("v4l2-ctl")
        if not self.disable_alsa:
            if self.udevadm == None:
                log('I can not find udevadm, so unable to identify devices.\n')
                log('Disabling both alsa and radiofunctionality.\n')
                self.disable_alsa = True

            elif self.ivtv_radio == None or self.ivtv_tune == None or self.v4l2_ctl == None:
                log('I can not find ivtv-tools and/or v4l-tools, so unable to play radio.\n')
                log('Disabling radiofunctionality.\n')
                self.disable_radio = True


    # end check_dependencies()

    def detect_radiodevice(self):
        video_devs = []
        for f in os.listdir('/dev/'):
            if f[:5] == 'video':
                video_devs.append(f)

        audio_cards = {}
        for id in range(len(alsaaudio.cards())):
            audio_cards[id] = RadioFunctions().query_udev_path(u'/dev/snd/controlC%s' % id, 'sound')

        self.radio_devs = []
        for f in os.listdir('/dev/'):
            if f[:5] == 'radio':
                devno = int(f[5:])
                radio_card = {}
                radio_card['radio_device'] = u'/dev/%s' % f
                radio_card['udevpath'] = RadioFunctions().query_udev_path('/dev/%s' % f, 'video4linux')
                if 'video%s' % devno in video_devs:
                    radio_card['video_device'] = u'/dev/video%s' % devno

                else:
                    radio_card['video_device'] = None

                if 'video%s' % (devno + 24) in video_devs:
                    radio_card['radio_out'] = u'/dev/video%s' % (devno + 24)
                    radio_card['radio_cardtype'] = 0
                    self.radio_devs.append(radio_card)
                    continue

                if radio_card['udevpath'] == None:
                    radio_card['radio_out'] = None
                    radio_card['radio_cardtype'] = 2
                    self.radio_devs.append(radio_card)
                    continue

                for id in range(len(alsaaudio.cards())):
                    if audio_cards[id] == radio_card['udevpath']:
                        radio_card['radio_out'] = alsaaudio.cards()[id]
                        radio_card['radio_cardtype'] = 1
                        break

                else:
                    radio_card['radio_out'] = self.select_card
                    radio_card['radio_cardtype'] = 2

                self.radio_devs.append(radio_card)

    # end detect_radiodevice()

    def get_alsa(self):

        if self.disable_alsa:
            return

        for cid in range(len(alsaaudio.cards())):
            self.alsa_names[alsaaudio.cards()[cid]] = cid
            self.alsa_cards[cid] = {}
            self.alsa_cards[cid]['name'] = alsaaudio.cards()[cid]
            self.alsa_cards[cid]['id'] = cid
            self.alsa_cards[cid]['mixers'] = {}
            for name in alsaaudio.mixers(cid):
                while True:
                    if name in self.alsa_cards[cid]['mixers'].keys():
                        mid +=1

                    else:
                        self.alsa_cards[cid]['mixers'][name] = {}
                        mid = 0

                    try:
                        mixer = alsaaudio.Mixer(control = name, id = mid, cardindex = cid)

                    except:
                        traceback.format_exc()
                        continue

                    self.alsa_cards[cid]['mixers'][name][mid] = {}
                    self.alsa_cards[cid]['mixers'][name][mid]['mixer'] = mixer
                    self.alsa_cards[cid]['mixers'][name][mid]['controls'] = []
                    if len(mixer.switchcap()) > 0:
                        try:
                            x = mixer.getmute()
                            self.alsa_cards[cid]['mixers'][name][mid]['controls'].append('mute')
                            self.alsa_cards[cid]['mixers'][name][mid]['mute'] = x

                        except:
                            traceback.format_exc()
                            pass

                        try:
                            x = mixer.getrec()
                            self.alsa_cards[cid]['mixers'][name][mid]['controls'].append('rec')
                            self.alsa_cards[cid]['mixers'][name][mid]['rec'] = x

                        except:
                            traceback.format_exc()
                            pass

                    if len(mixer.volumecap()) > 0:
                        try:
                            if self.alsa_version == '0.7':
                                x = mixer.getvolume('playback')
                            elif self.alsa_version == '0.8':
                                x = mixer.getvolume(alsaaudio.PCM_PLAYBACK)

                            self.alsa_cards[cid]['mixers'][name][mid]['controls'].append('volume')
                            self.alsa_cards[cid]['mixers'][name][mid]['volume'] = x

                        except:
                            traceback.format_exc()
                            pass

                        try:
                            if self.alsa_version == '0.7':
                                x = mixer.getvolume('capture')
                            elif self.alsa_version == '0.8':
                                x = mixer.getvolume(alsaaudio.PCM_CAPTURE)

                            self.alsa_cards[cid]['mixers'][name][mid]['controls'].append('capture')
                            self.alsa_cards[cid]['mixers'][name][mid]['capture'] = x

                        except:
                            traceback.format_exc()
                            pass

                    if len(mixer.getenum()) > 0:
                        self.alsa_cards[cid]['mixers'][name][mid]['controls'].append('enum')
                        self.alsa_cards[cid]['mixers'][name][mid]['value'] = mixer.getenum()[0]
                        self.alsa_cards[cid]['mixers'][name][mid]['values'] = mixer.getenum()[1]

                    break

    # end get_alsa()

    def set_mixer(self):

        if self.disable_alsa:
            return False

        if self.mixer != None:
            return True

        cid = RadioFunctions().get_cardid()
        if not cid in self.alsa_cards:
            return False

        if not self.opt_dict['audio_mixer'] in self.alsa_cards[cid]['mixers']:
            return False

        for id in self.alsa_cards[cid]['mixers'][self.opt_dict['audio_mixer']].keys():
            if not 'volume' in self.alsa_cards[cid]['mixers'][self.opt_dict['audio_mixer']][id]['controls']:
                log('The mixer %s is not a playback volume control\n' % self.opt_dict['audio_mixer'])
                return False

            if not 'mute' in self.alsa_cards[cid]['mixers'][self.opt_dict['audio_mixer']][id]['controls']:
                log('The mixer %s is not a playback mute control\n' % self.opt_dict['audio_mixer'])
                return False

            self.mixer = self.alsa_cards[cid]['mixers'][self.opt_dict['audio_mixer']][id]['mixer']
            return True

        return False

    # end set_mixer()

    def close(self):
        # close everything neatly
        if self.play_pcm != None:
            self.play_pcm.close()
            self.play_pcm = None

        if self.radio_pid != None:
            self.radio_pid.kill()
            self.radio_pid = None

        self.mixer = None
        for c in self.alsa_cards.values():
            c['name'] = None
            for m in c['mixers'].values():
                for i in m.values():
                    m['mixer'] = None

            pass

    # end close()

# end FunctionConfig()
config = FunctionConfig()

def log(message, log_level = 1, log_target = 3):
    """
    Log messages to log and/or screen
    """
    if config.log_queue == None:
        return

    config.log_queue.put([message, log_level, log_target])
# end log()

class AudioPCM(Thread):

    def __init__(self, card = None, capture = None):

        if config.disable_alsa:
            return

        Thread.__init__(self)
        self.quit = False
        if card == None:
            self.card = config.opt_dict['audio_card']

        else:
            self.card = card

        if capture == None:
            self.capture = config.opt_dict['radio_out']

        else:
            self.capture = capture

    def run(self):

        if config.disable_alsa or not config.opt_dict['radio_cardtype'] in (0, 1):
            return

        log('Starting Radioplayback from %s on %s.\n' % (config.opt_dict['radio_out'], self.card), 8)

        try:
            if config.opt_dict['radio_cardtype'] == 0:
                if config.alsa_version == '0.7':
                    PCM = alsaaudio.PCM(type = alsaaudio.PCM_PLAYBACK, mode = alsaaudio.PCM_NONBLOCK, card = self.card)

                elif config.alsa_version == '0.8' and 'pulse' in alsaaudio.pcms():
                    log('Using pulseaudio')
                    PCM = alsaaudio.PCM(type = alsaaudio.PCM_PLAYBACK, mode = alsaaudio.PCM_NONBLOCK, device = 'pulse')

                PCM.setformat(alsaaudio.PCM_FORMAT_S16_LE)
                PCM.setrate(48000)
                PCM.setchannels(2)
                PCM.setperiodsize(160)

                out = io.open(self.capture, 'rb')
                while True:
                    if self.quit:
                        log('Stoping Radioplayback from %s on %s.\n' % (config.opt_dict['radio_out'], self.card), 8)
                        out.close()
                        out = None
                        PCM = None
                        return

                    data = out.read(320)
                    PCM.write(data)

            elif config.opt_dict['radio_cardtype'] == 1:
                return
                #~ PCM = alsaaudio.PCM(type = alsaaudio.PCM_PLAYBACK, mode = alsaaudio.PCM_NONBLOCK, card = self.card)
                #~ PCM.setformat(alsaaudio.PCM_FORMAT_U8)
                #~ PCM.setrate(8000)
                #~ PCM.setchannels(2)
                #~ PCM.setperiodsize(160)

                out = alsaaudio.PCM(type = alsaaudio.PCM_CAPTURE, mode = alsaaudio.PCM_NONBLOCK, card = self.capture)
                #~ out.setformat(alsaaudio.PCM_FORMAT_U8)
                #~ out.setrate(8000)
                out.setformat(alsaaudio.PCM_FORMAT_S16_LE)
                out.setrate(48000)
                out.setchannels(2)
                out.setperiodsize(160)
                f = io.open('/home/mythtv/.ivtv/test.wav', 'wb')
                while True:
                    if self.quit:
                        log('Stoping Radioplayback from %s on %s.\n' % (config.opt_dict['radio_out'], self.card), 8)
                        f.close()
                        out = None
                        PCM = None
                        return

                    l, data = out.read()
                    f.write(data)
                    #~ if l:
                    #~ PCM.write(data)
                        #~ time.sleep(.001)

        except:
            log('Error Playing radio on %s\n' % (self.card))
            log(traceback.format_exc())
            out = None
            PCM = None
            return

    def close(self):
        self.quit = True

# end AudioPCM()

class RadioFunctions:
    """
    All functions to manipulate the radio and others
    """
    def rf_function_call(self, rf_call_id, command = None):
        if rf_call_id == 'Hibernate':
            if config.play_pcm != None or config.radio_pid != None:
                self.stop_radio()
                time.sleep(1)

        elif rf_call_id == 'Suspend':
            if config.play_pcm != None or config.radio_pid != None:
                self.stop_radio()
                time.sleep(1)

        elif rf_call_id == 'PlayRadio':
            self.start_radio()

        elif rf_call_id == 'StopRadio':
                self.stop_radio()

        elif rf_call_id == 'ToggleStartStop':
            if config.radio_pid != None:
                self.stop_radio()

            else:
                self.start_radio()

        elif rf_call_id == 'ChannelUp':
            self.channel_up()

        elif rf_call_id == 'ChannelDown':
            self.channel_down()

        elif rf_call_id == 'VolumeUp':
            self.radio_volume_up()

        elif rf_call_id == 'VolumeDown':
            self.radio_volume_down()

        elif rf_call_id == 'Mute':
            self.toggle_radio_mute()

        elif rf_call_id == 'CreateMythfmMenu':
            self.create_fm_menu_file()

    # end rf_function_call ()

    def query_backend(self, backend = None):
        """
        Check a MythTV backend for reaction
        """
        if backend == None:
            backend = config.opt_dict['myth_backend']

        URL0 = 'http://%s:6544//Myth/GetHostName' % (backend)
        try:
            response = ET.parse(urlopen(URL0))
            root = response.getroot()
            return root.text

        except:
            log('GetHostName failed, is the backend running?\n')
            return(-2)

    # end querybackend()

    def query_tuner(self, backend = None, video_device = None):
        """
        Query tunerstate with the backend
        Returns -2 Error
                     -1 Not Connected
                      0 Inactive
                      1 Watching LiveTV
                      7 Recording
        """
        if backend == None:
            backend = config.opt_dict['myth_backend']

        if video_device == None:
            video_device = config.opt_dict['video_device']

        hostname = self.query_backend(backend)
        if hostname == -2:
            return(-2)

        URL1 = 'http://%s:6544/Capture/GetCaptureCardList?HostName=%s' % (backend, hostname)
        try:
            response = ET.parse(urlopen(URL1))

        except:
            log('GetCaptureCardList failed, is the backend running?\n')
            return(-2)

        for element1 in response.findall('CaptureCards/CaptureCard'):
            if element1.findtext('VideoDevice') == video_device:
                URL2 = 'http://%s:6544/Dvr/GetEncoderList' % (backend)
                try:
                    response = ET.parse(urlopen(URL2))

                except:
                    log('GetEncoderList failed, is the backend running?\n')
                    return(-2)

                for element2 in response.findall('Encoders/Encoder'):
                    if element2.findtext('Id') == element1.findtext('CardId'):
                        return(int(element2.findtext('State')))
                        print(element2.findtext('State'))
                        break

                break
        log('The VideoCard is unknown to the MythBackend!\n')
        return(-1)

    # end querytuner()

    def query_udev_path(self, device, enddir = None):

        if not os.access(device, os.F_OK) or config.udevadm == None:
            return None

        if not device[:5] == '/dev/':
            return None

        udev_path = check_output([config.udevadm, 'info', '--query', 'path', '--name=%s' % device])
        if enddir == None:
            return udev_path

        else:
            returnpath = ''
            udev_path = re.split('/', udev_path)
            for dir in udev_path:
                if dir == enddir:
                    return returnpath

                returnpath += '/%s' % dir

            return returnpath

    # end query_udev_path()

    def get_device_ids(self, device):

        devpath = self.query_udev_path(device)
        if devpath == None:
            return None

        subsystem = ''
        name = ''
        driver = ''
        path = ''
        vendor = ''
        device = ''
        subvendor = ''
        subdevice = ''
        output = check_output([config.udevadm, 'info', '--attribute-walk', '--path=%s' % devpath])
        output = re.split('\n', output)
        for line in output:
            if line[:11] == 'SUBSYSTEM==':
                subsystem = re.sub('"', '', line[11:])

            elif line[:12] == 'ATTR{name}==':
                name = re.sub('"', '', line[12:])

            elif line[:9] == 'KERNELS==' and path == '' and line[10:13] != 'card':
                path = re.sub('"', '', line[9:])

            elif line[:9] == 'DRIVERS==' and driver == '':
                driver = re.sub('"', '', line[9:])

            elif line[:15] == 'ATTRS{vendor}==' and vendor == '':
                vendor = re.sub('"', '', line[15:])

            elif line[:15] == 'ATTRS{device}==' and device == '':
                device = re.sub('"', '', line[15:])

            elif line[:25] == 'ATTRS{subsystem_vendor}==' and subvendor == '':
                subvendor = re.sub('"', '', line[25:])

            elif line[:25] == 'ATTRS{subsystem_device}==' and subdevice == '':
                subdevice = re.sub('"', '', line[25:])

        return (subsystem, name, path, driver, vendor, device, subvendor, subdevice)

    # end get_device_id()

    def start_radio(self):
        log('Executing start_radio\n', 32)
        if config.disable_alsa or config.disable_radio:
            log('Alsa support disabled. Install the pyalsaaudio module\n')
            return

        tunerstatus =  self.query_tuner()
        if tunerstatus > 0:
            log('MythTV is using the tuner!\n')
            return

        if config.radio_pid != None:
            return

        log('Starting ivtv-radio channel %s on %s.\n' % (config.channels[config.active_channel]['title'], config.opt_dict['radio_device']), 8)
        try:
            config.radio_pid = Popen(executable = config.ivtv_radio, stderr = config.stderr_write, \
                                args = ['-d %s' % config.opt_dict['radio_device'], '-j', '-f %s' % config.channels[config.active_channel]['frequency']])

        except:
            log('Error Starting %s:\n' % (config.ivtv_radio))
            log(traceback.format_exc())

        if config.opt_dict['radio_cardtype'] in (0, 1):
            try:
                config.play_pcm = AudioPCM()
                config.play_pcm.start()

            except:
                log('Error Starting Playback:\n')
                log(traceback.format_exc())

        elif config.opt_dict['radio_cardtype'] == 2:
            log('%s sset "%s" %s\n' % (self.get_cardid(), config.opt_dict['source_switch'], config.opt_dict['source']))
            try:
                check_call(['amixer', '--quiet', '--card=%s' % self.get_cardid(), 'sset', '"%s"'  % (config.opt_dict['source_switch']), config.opt_dict['source']])

            except:
                log('Error Selecting Source:\n')
                log(traceback.format_exc())

        config.mixer.setvolume(config.retrieve_value('RadioVolume',70))
        config.mixer.setmute(0)

    # end start_radio()

    def stop_radio(self):
        log('Executing stop_radio\n', 32)
        if config.disable_alsa or config.disable_radio:
            log('Alsa support disabled. Install the pyalsaaudio module\n')
            return

        if config.play_pcm != None:
            config.play_pcm.close()
            config.play_pcm = None

        if config.radio_pid != None:
            config.radio_pid.terminate()
            config.radio_pid = None

    # end stop_radio()

    def select_channel(self, channel):
        if 0 < channel <= len(config.channels):
            # It's a Radio Channelnumber
            config.new_channel = channel
            self.set_channel()

        elif 800 <channel < 1100:
            # It's a radio frequency *10
            frequency = float(channel)/10
            if frequency in config.frequencies.keys():
                config.new_channel = config.frequencies[frequency]
                self.set_channel()

        elif channel > 1100:
            # It's a TV Channel *1000
            self.tune_tv(int(channel/1000))

    # end select_channel()

    def channel_up(self):
        log('Executing channel_up\n', 32)
        config.new_channel = config.active_channel + 1
        if config.new_channel > len(config.channels):
            config.new_channel = 1

        self.set_channel()

    # end channel_up()

    def channel_down(self):
        log('Executing channel_down\n', 32)
        config.new_channel = config.active_channel - 1
        if config.new_channel < 1:
            config.new_channel = len(config.channels)

        self.set_channel()

    # end channel_down()

    def get_active_frequency(self):
        if config.disable_radio:
            log('Radio support disabled. Install the ivtv/v4l Utilities\n')
            return

        try:
            freq = check_output([config.v4l2_ctl, '--device=%s' % config.opt_dict['radio_device'], '--get-freq'])
            freq = re.search('.*?\((.*?) MHz', freq)
            if freq != None:
               return float(freq.group(1))

            else:
                log('Error retreiving frequency from %s\n' % config.opt_dict['radio_device'])

        except:
            log('Error retreiving frequency from %s\n' % config.opt_dict['radio_device'])
            log(traceback.format_exc())

    # end get_active_frequency()

    def set_channel(self):
        if config.disable_radio:
            log('Radio support disabled. Install the ivtv/v4l Utilities\n')
            return

        if config.radio_pid == None:
            self.start_radio()

        if config.active_channel == config.new_channel:
            return

        try:
            chanid = config.channels[config.new_channel]
            log('Setting frequency for %s to %3.1f MHz(%s)\n' % (config.opt_dict['radio_device'], chanid['frequency'], chanid['title']), 8)
            check_call([config.v4l2_ctl, '--device=%s' % config.opt_dict['radio_device'], '--set-freq=%s' % chanid['frequency']])
            config.active_channel = config.new_channel
            config.save_value('LastChannel', config.active_channel)

        except:
            log('Error setting frequency for %s\n' % config.opt_dict['radio_device'])
            log(traceback.format_exc())

    # end set_channel()

    def tune_tv(self, frequency):
        if config.disable_radio:
            log('Radio support disabled. Install the ivtv/v4l Utilities\n')
            return

        tunerstatus =  query_tuner()
        if tunerstatus < 0:
            return

        if tunerstatus > 0:
            log('The videotuner is busy!\n')
            return

        try:
            check_call([config.ivtv_tune, '--device=%s' % config.opt_dict['video_device'], '--frequency=%s' % frequency])
            time.sleep(1)
            check_call([config.ivtv_tune, '--device=%s' % config.opt_dict['video_device'], '--frequency=%s' % frequency])
            log('Setting frequency for %s to %3.1f KHz\n' % (config.opt_dict['video_device'], frequency), 8)

        except:
            log('Error setting frequency for %s\n' % config.opt_dict['video_device'])
            log(traceback.format_exc())

    # end tune_tv()

    def detect_channels(self, radio_dev = None):
        if config.disable_radio:
            return []

        freq_list = []
        if radio_dev == None and 'radio_device' in config.opt_dict:
            radio_dev = config.opt_dict['radio_device']

        try:
            read_list = check_output([config.ivtv_radio, '-d', radio_dev, '-s'])
            read_list = re.split('\n',read_list)
            for freq in read_list:
                if freq == '':
                    continue

                freq = re.split(' ', freq)
                freq_list.append(float(freq[1]))

            return freq_list

        except:
            return []

    # end detect_channels()

    def get_alsa_cards(self, cardid = None):
        if config.disable_alsa:
            return []

        if cardid == None:
            return alsaaudio.cards()

        elif cardid < len(alsaaudio.cards()):
            return alsaaudio.cards()[cardid]

    # end get_alsa_cards()

    def get_alsa_mixers(self, cardid = 0, mixerid = None):
        if config.disable_alsa:
            return []

        if cardid < len(alsaaudio.cards()):
            if mixerid == None:
                return alsaaudio.mixers(cardid)

            elif mixerid < len(alsaaudio.mixers(cardid)):
                return alsaaudio.mixers(cardid)[mixerid]

    # end get_alsa_mixers()

    def get_alsa_pcms(self, playback = True):
        if config.disable_alsa:
            return []

        if playback:
            return alsaaudio.pcms()

        else:
            return alsaaudio.pcms(alsaaudio.PCM_CAPTURE)

    # end get_alsa_mixers()

    def get_cardid(self, audiocard = None):
        if config.disable_alsa:
            return -1

        if audiocard == None:
            audiocard = config.opt_dict['audio_card']

        for id in range(len(alsaaudio.cards())):
            if alsaaudio.cards()[id] == audiocard:
                return id

        return -1
    # end get_cardid()

    def get_volume(self, cardnr = 0, mixer_ctrl = 'Master', id = 0, playback = True):
        if config.disable_alsa:
            return

        if playback and 'volume' in config.alsa_cards[cardnr]['mixers'][mixer_ctrl][id]['controls']:
            if config.alsa_version == '0.7':
                return alsaaudio.Mixer(mixer_ctrl, id, cardnr).getvolume('playback')
            elif config.alsa_version == '0.8':
                return alsaaudio.Mixer(mixer_ctrl, id, cardnr).getvolume(alsaaudio.PCM_PLAYBACK)

        if (not playback) and 'capture' in config.alsa_cards[cardnr]['mixers'][mixer_ctrl][id]['controls']:
            if config.alsa_version == '0.7':
                return alsaaudio.Mixer(mixer_ctrl, id, cardnr).getvolume('capture')
            elif config.alsa_version == '0.8':
                return alsaaudio.Mixer(mixer_ctrl, id, cardnr).getvolume(alsaaudio.PCM_CAPTURE)

        return None

    # end get_volume()

    def set_volume(self, cardnr = 0, mixer_ctrl = 'Master', id = 0, playback = True, volume = 0):
        if config.disable_alsa:
            return

        if playback and 'volume' in config.alsa_cards[cardnr]['mixers'][mixer_ctrl][id]['controls']:
            log('Setting playbackvolume for %s on %s to %s.\n' % (mixer_ctrl, config.alsa_cards[cardnr]['name'], volume), 16)
            if config.alsa_version == '0.7':
                alsaaudio.Mixer(mixer_ctrl, id, cardnr).setvolume(volume, direction = 'playback')

            elif config.alsa_version == '0.8':
                alsaaudio.Mixer(mixer_ctrl, id, cardnr).setvolume(volume, direction = alsaaudio.PCM_PLAYBACK)

            config.save_value('%s_%s_Volume' % (config.alsa_cards[cardnr]['name'], mixer_ctrl),volume)

        elif (not playback) and 'capture' in config.alsa_cards[cardnr]['mixers'][mixer_ctrl][id]['controls']:
            log('Setting capturevolume for %s on %s to %s.\n' % (mixer_ctrl, config.alsa_cards[cardnr]['name'], volume), 16)
            if config.alsa_version == '0.7':
                alsaaudio.Mixer(mixer_ctrl, id, cardnr).setvolume(volume, direction = 'capture')

            elif config.alsa_version == '0.8':
                alsaaudio.Mixer(mixer_ctrl, id, cardnr).setvolume(volume, direction = alsaaudio.PCM_CAPTURE)

            config.save_value('%s_%s_Volume' % (config.alsa_cards[cardnr]['name'], mixer_ctrl),volume)

    # end set_volume()

    def get_mute(self, cardnr = 0, mixer_ctrl = 'Master', id = 0, playback = True):
        if config.disable_alsa:
            return

        if playback and 'mute' in config.alsa_cards[cardnr]['mixers'][mixer_ctrl][id]['controls']:
            return alsaaudio.Mixer(mixer_ctrl, id, cardnr).getrec()

        if (not playback) and 'rec' in config.alsa_cards[cardnr]['mixers'][mixer_ctrl][id]['controls']:
            return alsaaudio.Mixer(mixer_ctrl, id, cardnr).getrec()

        return None

    # end get_mute()

    def set_mute(self, cardnr = 0, mixer_ctrl = 'Master', id = 0, playback = True, muteval = True):
        if config.disable_alsa:
            return

        if muteval:
            val = 1

        else:
            val = 0

        if playback and 'volume' in config.alsa_cards[cardnr]['mixers'][mixer_ctrl][id]['controls']:
            log('%s playbackvolume for %s on %s.\n' % (config.mutetext[val], mixer_ctrl, config.alsa_cards[cardnr]['name']), 16)
            alsaaudio.Mixer(mixer_ctrl, id, cardnr).setmute(val)

        elif (not playback) and 'capture' in config.alsa_cards[cardnr]['mixers'][mixer_ctrl][id]['controls']:
            log('%s capturevolume for %s on %s.\n' % (config.mutetext[val], mixer_ctrl, config.alsa_cards[cardnr]['name']), 16)
            alsaaudio.Mixer(mixer_ctrl, id, cardnr).setrec(val)

    # end set_mute()

    def radio_volume_up(self):
        log('Executing radio_volume_up\n', 32)
        if config.disable_alsa:
            return

        vol_list = config.mixer.getvolume()
        vol = 0
        for v in vol_list:
            vol += v
        vol = vol/len(vol_list)
        vol += 5
        if vol > 100:
            vol = 100

        log('Setting playbackvolume for %s on %s to %s.\n' % (config.opt_dict['audio_mixer'], config.opt_dict['audio_card'], vol), 16)
        config.mixer.setvolume(vol)
        config.save_value('RadioVolume',vol)
        return

    # end radio_volume_up()

    def radio_volume_down(self):
        log('Executing radio_volume_down\n', 32)
        if config.disable_alsa:
            return

        vol_list = config.mixer.getvolume()
        vol = 0
        for v in vol_list:
            vol += v
        vol = vol/len(vol_list)
        vol -= 5
        if vol < 0:
            vol = 0

        log('Setting playbackvolume for %s on %s to %s.\n' % (config.opt_dict['audio_mixer'], config.opt_dict['audio_card'], vol), 16)
        config.mixer.setvolume(vol)
        config.save_value('RadioVolume',vol)
        return

    # end radio_volume_down()

    def toggle_radio_mute(self):
        log('Executing toggle_radio_mute\n', 32)
        if config.disable_alsa:
            return

        mute = config.mixer.getmute()[0]
        mute = 1 - mute
        log('%s playbackvolume for %s on %s.\n' % (config.mutetext[mute], config.opt_dict['audio_mixer'], config.opt_dict['audio_card']), 16)
        config.mixer.setmute(mute)
        return

    # end toggle_radio_mute()

    def create_fm_menu_file(self):
        log('Executing create_fm_menu_file\n', 32)
        #~ if len(config.channels) == 0:
            #~ return

        file = '%s/fmmenu.xml' % config.ivtv_dir
        if os.path.exists(file):
            os.rename(file, file + '.old')

        try:
            f = io.open(file, 'w')

            f.write(u'<?xml version=\"1.0\" encoding=\"UTF-8\" ?>\n')
            f.write(u'<mythmenu name=\"FMMENU\">\n')
            f.write(u'\n')
            for c, channel in config.channels.items():
                f.write(u'   <button>\n')
                f.write(u'      <type>MUSIC</type>\n')
                f.write(u'      <text>%s</text>\n' % (channel['title']))
                f.write(u'      <action>EXEC echo "%s" > "%s"</action>\n' % (c, config.opt_dict['fifo_file']))
                f.write(u'   </button>\n')
                f.write(u'\n')

            f.write(u'   <button>\n')
            f.write(u'      <type>MUSIC</type>\n')
            f.write(u'      <text>Start/Stop de Radio</text>\n')
            f.write(u'      <action>EXEC echo "start_stop_radio" > "%s"</action>\n' % (config.opt_dict['fifo_file']))
            f.write(u'   </button>\n')
            f.write(u'\n')
            f.write(u'</mythmenu>\n')
            f.write(u'\n')

            f.close()

        except:
            log('failed to create menufile %s\n' % file)
            log(traceback.format_exc())

# end RadioFunctions()

