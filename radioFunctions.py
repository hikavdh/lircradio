#!/usr/bin/env python2
# -*- coding: utf-8 -*-

description_text = """

"""

import sys, io, os, datetime, time, random
import re, codecs, locale, pwd
import socket, urllib2, sys
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
        self.minor = 2
        self.patch = 1
        self.beta = True

        self.functioncalls = {u'poweroff'                  :u'PowerOff',
                                         u'reboot'                      :u'Reboot',
                                         u'hibernate'                :u'Hibernate',
                                         u'suspend'                    :u'Suspend',
                                         u'play_radio'              :u'PlayRadio',
                                         u'stop_radio'              :u'StopRadio',
                                         u'start_stop_radio'  :u'ToggleStartStop',
                                         u'Ch+'                            :u'ChannelUp',
                                         u'Ch-'                            :u'ChannelDown',
                                         u'V+'                              :u'VolumeUp',
                                         u'V-'                              :u'VolumeDown',
                                         u'mute'                          :u'Mute',
                                         u'create_mythfmmenu':u'CreateMythfmMenu'}
                                         #~ u'':u'',
        self.call_list = {}
        for v in self.functioncalls.values():
            self.call_list[v.lower()] = v

        self.mutetext = {}
        self.mutetext[0] = 'Unmuting'
        self.mutetext[1] = 'Muting'

        self.channels = {}
        self.frequencies = {}
        self.opt_dict = {}
        self.opt_dict['verbose'] = True

        self.max_logsize = 1048576
        self.max_logcount = 5
        self.log_level = 1
        self.log_file = ''
        self.log_output = None

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

        self.active_channel = 1
        self.new_channel = 0
        self.radio_pid = None
        self.play_pcm = None
        self.mixer = None
        self.audio_out = None

    # end Init()

    def version(self, as_string = False):
        if as_string and self.beta:
            return u'%s Version: %s.%s.%s-beta' % (self.name, self.major, self.minor, self.patch)

        if as_string and not self.beta:
            return u'%s Version: %s.%s.%s' % (self.name, self.major, self.minor, self.patch)

        else:
            return (self.name, self.major, self.minor, self.patch, self.beta)

    # end version()

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
            log('Can not save %s/%s. Check access rights' % (self.ivtv_dir, name) )

        try:
            f = io.open('%s/%s' % (self.ivtv_dir, name), 'wb')
            f.write('%s\n' % value)
            f.close()

        except:
            log('Can not save %s/%s. Check access rights' % (self.ivtv_dir, name) )

    # end save_value()

    def check_dependencies(self, ivtv_dir):

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

        self.ivtv_dir = ivtv_dir
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

        poweroff = check_path("poweroff", True)
        reboot = check_path("reboot", True)
        hibernate_ram = check_path("hibernate-ram", True)
        hibernate = check_path("hibernate", True)
        pm_suspend = check_path("pm-suspend", True)
        pm_hibernate =check_path("pm-hibernate", True)

        # Checking for the presence of Commands.sh
        if os.access(self.ivtv_dir + '/Commands.sh', os.F_OK):
            if not os.access(self.ivtv_dir + '/Commands.sh', os.X_OK):
                os.chmod(self.ivtv_dir + '/Commands.sh', 0750)

            self.command_name = self.ivtv_dir + '/Commands.sh'

        elif os.access('/usr/bin/Commands.sh', os.X_OK):
            self.command_name = '/usr/bin/Commands.sh'

        else:
            f = io.open(self.ivtv_dir + '/Commands.sh', 'wb')
            f.write('#!/bin/bash\n')
            f.write('\n')
            f.write('Command=${1:-""}\n')
            f.write('\n')
            f.write('case $Command in\n')
            f.write('    "poweroff")\n')
            f.write('    # The command to execute on poweroff\n')
            if poweroff != None:
                f.write('    sudo %s\n' % poweroff)

            else:
                f.write('#    sudo poweroff\n')

            f.write('    ;;\n')
            f.write('    "reboot")\n')
            f.write('    # The command to execute on reboot\n')
            if reboot != None:
                f.write('    sudo %s\n' % reboot)

            else:
                f.write('#    sudo reboot\n')

            f.write('    ;;\n')
            f.write('    "suspend")\n')
            f.write('    # The command to execute on suspend\n')
            if hibernate_ram != None:
                f.write('    sudo %s\n' % hibernate_ram)
                if pm_suspend != None:
                    f.write('#    sudo %s\n' % pm_suspend)

            elif pm_suspend != None:
                f.write('    sudo %s\n' % pm_suspend)

            else:
                f.write('#    sudo pm_suspend\n')

            f.write('    ;;\n')
            f.write('    "hibernate")\n')
            f.write('    # The command to execute on hibernate\n')
            if hibernate != None:
                f.write('    sudo %s\n' % hibernate)
                if pm_hibernate != None:
                    f.write('#    sudo %s\n' % pm_hibernate)

            elif pm_hibernate != None:
                f.write('    sudo %s\n' % pm_hibernate)

            else:
                f.write('#    sudo pm_hibernate\n')

            f.write('    ;;\n')
            f.write('esac   \n')
            f.write('\n')
            f.close()
            self.command_name = self.ivtv_dir + '/Commands.sh'
            os.chmod(self.command_name, 0750)


    # end check_dependencies()

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
                            pass

                        try:
                            x = mixer.getrec()
                            self.alsa_cards[cid]['mixers'][name][mid]['controls'].append('rec')
                            self.alsa_cards[cid]['mixers'][name][mid]['rec'] = x

                        except:
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
                            pass

                        try:
                            if self.alsa_version == '0.7':
                                x = mixer.getvolume('capture')
                            elif self.alsa_version == '0.8':
                                x = mixer.getvolume(alsaaudio.PCM_CAPTURE)

                            self.alsa_cards[cid]['mixers'][name][mid]['controls'].append('capture')
                            self.alsa_cards[cid]['mixers'][name][mid]['capture'] = x

                        except:
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
                log('The mixer %s is not a playback volume control' % self.opt_dict['audio_mixer'])
                return False

            if not 'mute' in self.alsa_cards[cid]['mixers'][self.opt_dict['audio_mixer']][id]['controls']:
                log('The mixer %s is not a playback mute control' % self.opt_dict['audio_mixer'])
                return False

            self.mixer = self.alsa_cards[cid]['mixers'][self.opt_dict['audio_mixer']][id]['mixer']
            return True

        return False

    # end set_mixer()

    def rotate_log(self):
        if  self.log_output == None or self.log_file == '':
            return

        self.log_output.flush()
        if os.stat(self.log_file).st_size < self.max_logsize:
            return

        self.log_output.close()
        if os.access('%s.%s' % (self.log_file, self.max_logcount), os.F_OK):
            os.remove('%s.%s' % (self.log_file, self.max_logcount))

        for i in range(self.max_logcount - 1, 0, -1):
            if os.access('%s.%s' % (self.log_file, i), os.F_OK):
                os.rename('%s.%s' % (self.log_file, i), '%s.%s' % (self.log_file, i + 1))

        os.rename(self.log_file, '%s.1' % (self.log_file))

        self.log_output =  io.open(self.log_file, mode = 'ab', encoding = 'utf-8')
        sys.stderr = self.log_output

    # end rotate_log()

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

        try:
            self.log_output.close()

        except:
            pass

    # end close()

# end FunctionConfig()
config = FunctionConfig()

def log(message, log_level = 1, log_target = 3):
    """
    Log messages to log and/or screen
    """
    def now():
         return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z') + ': '

    if type(message) != unicode:
        message = unicode(message)

    # Log to the screen
    if log_level == 0 or ((config.opt_dict['verbose']) and (log_level & config.log_level) and (log_target & 1)):
        sys.stdout.write(message.encode("utf-8"))

    # Log to the log-file
    if (log_level == 0 or ((log_level & config.log_level) and (log_target & 2))) and config.log_output != None:
        message = u'%s%s\n' % (now(), message.replace('\n',''))
        sys.stderr.write(message.encode("utf-8"))

    config.rotate_log()
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

        log('Starting Radioplayback from %s on %s.' % (config.opt_dict['radio_out'], self.card), 8)

        try:
            if config.opt_dict['radio_cardtype'] == 0:
                PCM = alsaaudio.PCM(type = alsaaudio.PCM_PLAYBACK, mode = alsaaudio.PCM_NONBLOCK, card = self.card)
                PCM.setformat(alsaaudio.PCM_FORMAT_S16_LE)
                PCM.setrate(48000)
                PCM.setchannels(2)
                PCM.setperiodsize(160)

                out = io.open(self.capture, 'rb')
                while True:
                    if self.quit:
                        log('Stoping Radioplayback from %s on %s.' % (config.opt_dict['radio_out'], self.card), 8)
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
                        log('Stoping Radioplayback from %s on %s.' % (config.opt_dict['radio_out'], self.card), 8)
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
            log('Error: %s Playing radio on %s' % (sys.exc_info()[1], self.card))
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
        if rf_call_id == 'Command'and config.command_name != None and command != None:
            log('Executing %s %s' % (config.command_name, command), 32)
            call([config.command_name, command])

        elif rf_call_id == 'PowerOff'and config.command_name != None:
            log('Executing %s %s' % (config.command_name, 'poweroff'), 32)
            call([config.command_name,'poweroff'])

        elif rf_call_id == 'Reboot'and config.command_name != None:
            log('Executing %s %s' % (config.command_name, 'reboot'), 32)
            call([config.command_name,'reboot'])

        elif rf_call_id == 'Hibernate'and config.command_name != None:
            log('Executing %s %s' % (config.command_name, 'hibernate'), 32)
            if config.play_pcm != None or config.radio_pid != None:
                self.stop_radio()
                time.sleep(1)

            call([config.command_name,'hibernate'])

        elif rf_call_id == 'Suspend'and config.command_name != None:
            log('Executing %s %s' % (config.command_name, 'suspend'), 32)
            if config.play_pcm != None or config.radio_pid != None:
                self.stop_radio()
                time.sleep(1)

            call([config.command_name,'suspend'])

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
            self.create_fm_menu_file(command[0], command[1])

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
            log('GetCaptureCardList failed, is the backend running?')
            return(-2)

        for element1 in response.findall('CaptureCards/CaptureCard'):
            if element1.findtext('VideoDevice') == video_device:
                URL2 = 'http://%s:6544/Dvr/GetEncoderList' % (backend)
                try:
                    response = ET.parse(urlopen(URL2))

                except:
                    log('GetEncoderList failed, is the backend running?')
                    return(-2)

                for element2 in response.findall('Encoders/Encoder'):
                    if element2.findtext('Id') == element1.findtext('CardId'):
                        return(int(element2.findtext('State')))
                        print(element2.findtext('State'))
                        break

                break
        log('The VideoCard is unknown to the MythBackend!')
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
        log('Executing start_radio', 32)
        if config.disable_alsa or config.disable_radio:
            log('Alsa support disabled. Install the pyalsaaudio module')
            return

        tunerstatus =  self.query_tuner()
        if tunerstatus > 0:
            log('MythTV is using the tuner!')
            return

        if config.radio_pid != None:
            return

        log('Starting ivtv-radio channel %s on %s.' % (config.channels[config.active_channel]['title'], config.opt_dict['radio_device']), 8)
        try:
            config.radio_pid = Popen(executable = config.ivtv_radio, stderr = config.log_output, \
                                args = ['-d %s' % config.opt_dict['radio_device'], '-j', '-f %s' % config.channels[config.active_channel]['frequency']])

        except:
            log('Error: %s Starting %s' % (sys.exc_info()[1], config.ivtv_radio))

        if config.opt_dict['radio_cardtype'] in (0, 1):
            try:
                config.play_pcm = AudioPCM()
                config.play_pcm.start()

            except:
                log('Error: %s, Starting Playback' % (sys.exc_info()[1]))

        elif config.opt_dict['radio_cardtype'] == 2:
            log('%s sset "%s" %s' % (self.get_cardid(), config.opt_dict['source_switch'], config.opt_dict['source']))
            try:
                check_call(['amixer', '--quiet', '--card=%s' % self.get_cardid(), 'sset', '"%s"'  % (config.opt_dict['source_switch']), config.opt_dict['source']])

            except:
                log('Error: %s, Selecting Source' % (sys.exc_info()[1]))

        config.mixer.setvolume(config.retrieve_value('RadioVolume',70))
        config.mixer.setmute(0)

    # end start_radio()

    def stop_radio(self):
        log('Executing stop_radio', 32)
        if config.disable_alsa or config.disable_radio:
            log('Alsa support disabled. Install the pyalsaaudio module')
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
        log('Executing channel_up', 32)
        config.new_channel = config.active_channel + 1
        if config.new_channel > len(config.channels):
            config.new_channel = 1

        self.set_channel()

    # end channel_up()

    def channel_down(self):
        log('Executing channel_down', 32)
        config.new_channel = config.active_channel - 1
        if config.new_channel < 1:
            config.new_channel = len(config.channels)

        self.set_channel()

    # end channel_down()

    def get_active_frequency(self):
        if config.disable_radio:
            log('Radio support disabled. Install the ivtv/v4l Utilities')
            return

        try:
            freq = check_output([config.v4l2_ctl, '--device=%s' % config.opt_dict['radio_device'], '--get-freq'])
            freq = re.search('.*?\((.*?) MHz', freq)
            if freq != None:
               return float(freq.group(1))

            else:
                log('Error retreiving frequency from %s' % config.opt_dict['radio_device'])

        except:
            log('Error retreiving frequency from %s' % config.opt_dict['radio_device'])

    # end get_active_frequency()

    def set_channel(self):
        if config.disable_radio:
            log('Radio support disabled. Install the ivtv/v4l Utilities')
            return

        if config.radio_pid == None:
            self.start_radio()

        if config.active_channel == config.new_channel:
            return

        try:
            chanid = config.channels[config.new_channel]
            log('Setting frequency for %s to %3.1f MHz(%s)' % (config.opt_dict['radio_device'], chanid['frequency'], chanid['title']), 8)
            check_call([config.v4l2_ctl, '--device=%s' % config.opt_dict['radio_device'], '--set-freq=%s' % chanid['frequency']])
            config.active_channel = config.new_channel
            config.save_value('LastChannel', config.active_channel)

        except:
            log('Error setting frequency for %s' % config.opt_dict['radio_device'])

    # end set_channel()

    def tune_tv(self, frequency):
        if config.disable_radio:
            log('Radio support disabled. Install the ivtv/v4l Utilities')
            return

        tunerstatus =  query_tuner()
        if tunerstatus < 0:
            return

        if tunerstatus > 0:
            log('The videotuner is busy!')
            return

        try:
            check_call([config.ivtv_tune, '--device=%s' % config.opt_dict['video_device'], '--frequency=%s' % frequency])
            time.sleep(1)
            check_call([config.ivtv_tune, '--device=%s' % config.opt_dict['video_device'], '--frequency=%s' % frequency])
            log('Setting frequency for %s to %3.1f KHz' % (config.opt_dict['video_device'], frequency), 8)

        except:
            log('Error setting frequency for %s' % config.opt_dict['video_device'])

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
            log('Setting playbackvolume for %s on %s to %s.' % (mixer_ctrl, config.alsa_cards[cardnr]['name'], volume), 16)
            if config.alsa_version == '0.7':
                alsaaudio.Mixer(mixer_ctrl, id, cardnr).setvolume(volume, direction = 'playback')

            elif config.alsa_version == '0.8':
                alsaaudio.Mixer(mixer_ctrl, id, cardnr).setvolume(volume, direction = alsaaudio.PCM_PLAYBACK)

            config.save_value('%s_%s_Volume' % (config.alsa_cards[cardnr]['name'], mixer_ctrl),volume)

        elif (not playback) and 'capture' in config.alsa_cards[cardnr]['mixers'][mixer_ctrl][id]['controls']:
            log('Setting capturevolume for %s on %s to %s.' % (mixer_ctrl, config.alsa_cards[cardnr]['name'], volume), 16)
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
            log('%s playbackvolume for %s on %s.' % (config.mutetext[val], mixer_ctrl, config.alsa_cards[cardnr]['name']), 16)
            alsaaudio.Mixer(mixer_ctrl, id, cardnr).setmute(val)

        elif (not playback) and 'capture' in config.alsa_cards[cardnr]['mixers'][mixer_ctrl][id]['controls']:
            log('%s capturevolume for %s on %s.' % (config.mutetext[val], mixer_ctrl, config.alsa_cards[cardnr]['name']), 16)
            alsaaudio.Mixer(mixer_ctrl, id, cardnr).setrec(val)

    # end set_mute()

    def radio_volume_up(self):
        log('Executing radio_volume_up', 32)
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

        log('Setting playbackvolume for %s on %s to %s.' % (config.opt_dict['audio_mixer'], config.opt_dict['audio_card'], vol), 16)
        config.mixer.setvolume(vol)
        config.save_value('RadioVolume',vol)
        return

    # end radio_volume_up()

    def radio_volume_down(self):
        log('Executing radio_volume_down', 32)
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

        log('Setting playbackvolume for %s on %s to %s.' % (config.opt_dict['audio_mixer'], config.opt_dict['audio_card'], vol), 16)
        config.mixer.setvolume(vol)
        config.save_value('RadioVolume',vol)
        return

    # end radio_volume_down()

    def toggle_radio_mute(self):
        log('Executing toggle_radio_mute', 32)
        if config.disable_alsa:
            return

        mute = config.mixer.getmute()[0]
        mute = 1 - mute
        log('%s playbackvolume for %s on %s.' % (config.mutetext[mute], config.opt_dict['audio_mixer'], config.opt_dict['audio_card']), 16)
        config.mixer.setmute(mute)
        return

    # end toggle_radio_mute()

    def create_fm_menu_file(self, ivtv_dir, fifo):
        log('Executing create_fm_menu_file', 32)
        #~ if len(config.channels) == 0:
            #~ return

        file = '%s/fmmenu.xml' % ivtv_dir
        try:
            os.rename(file, file + '.old')
        except:
            pass

        try:
            f = io.open(file, 'w')

            f.write(u'<?xml version=\"1.0\" encoding=\"UTF-8\" ?>\n')
            f.write(u'<mythmenu name=\"FMMENU\">\n')
            f.write(u'\n')
            for c, channel in config.channels.items():
                f.write(u'   <button>\n')
                f.write(u'      <type>MUSIC</type>\n')
                f.write(u'      <text>%s</text>\n' % (channel['title']))
                f.write(u'      <action>EXEC echo "%s" > "%s"</action>\n' % (c, fifo))
                f.write(u'   </button>\n')
                f.write(u'\n')

            f.write(u'   <button>\n')
            f.write(u'      <type>MUSIC</type>\n')
            f.write(u'      <text>Start/Stop de Radio</text>\n')
            f.write(u'      <action>EXEC echo "start_stop_radio" > "%s"</action>\n' % (fifo))
            f.write(u'   </button>\n')
            f.write(u'\n')
            f.write(u'</mythmenu>\n')
            f.write(u'\n')

            f.close()

        except Exception as e:
            log('failed to create menufile %s' % file)

# end RadioFunctions()

