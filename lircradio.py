#!/usr/bin/env python2
# -*- coding: utf-8 -*-

description_text = """
    This script listens to commands comming in through a fifopipe.
    In reaction commands in radioFunctions.py are executed.
    It also starts an ircat daemon that puts lirc commands into the pipe,
    but very nice you can also do this through ssh, remotely starting
    your radio or suspending a machine, without locking up your console:

        ssh pc-x "echo suspend > /tmp/hika-fiforadio"

    Possible commands are among others to run a suspend script,
    start a radiodevice and manage audio volume.
    It also can check mythtv for availability of the radio device.
    The latest version can be found at:

        https://github.com/hikavdh/lircradio

"""

import sys, io, os, pwd
import re, codecs, locale
import socket, argparse
from stat import *
from threading import Thread
try:
    from subprocess32 import *
except:
    from subprocess import *
try:
    from radioFunctions import log
    from radioFunctions import config as rfconf
    from radioFunctions import RadioFunctions as rfcalls
except:
    print "I cannot load radioFunctions.py. Make sure it's in the same directory!"
    sys.exit(2)

# check Python version
if sys.version_info[:2] < (2,6):
    sys.stderr.write("lircradio requires Pyton 2.6 or higher\n")
    sys.exit(2)

elif sys.version_info[:2] >= (3,0):
    sys.stderr.write("lircradio does not support Pyton 3 or higher.\nExpect errors while we proceed\n")

if rfconf.version()[:2] < (0,1):
    sys.stderr.write("lircradio requires radioFunctions 0.1 or higher\n")
    sys.exit(2)

class Configure:
    """This class holds all configuration details and manages file IO"""

    def __init__(self):

        self.name ='lircradio.py'
        self.major = 0
        self.minor = 1
        self.patch = 1
        self.beta = True

        self.write_info_files = False
        #  1=Log System Actions and errors
        #  2=Log all commands coming through the pipe, Mainly for debugging
        #  4=log unknown commands coming through the pipe
        #  8=log Channel changes
        # 16=log Volume changes
        # 32=log all radiofunction calls, Mainly for debugging
        rfconf.log_level = 29

        self.opt_dict = {}
        self.file_encoding = 'utf-8'

        # default configuration file locations
        self.hpath = ''
        if 'HOME' in os.environ:
            self.hpath = os.environ['HOME']
        # extra test for windows users
        elif 'HOMEPATH' in os.environ:
            self.hpath = os.environ['HOMEPATH']

        self.username = pwd.getpwuid(os.getuid())[0]

        self.ivtv_dir = u'%s/.ivtv' % self.hpath
        # check for the ~.ivtv dir
        if not os.path.exists(self.ivtv_dir):
            log('Creating %s directory,' % self.ivtv_dir)
            os.mkdir(self.ivtv_dir)

        self.etc_dir = u'/etc/lircradio'
        self.config_file =u'/radioFunctions.conf'
        self.log_file = u'%s/lircradio.log' % self.ivtv_dir
        self.myth_menu_file = 'fmmenu.xml'
        self.opt_dict['verbose'] = False

        #self.opt_dict[''] =
        self.opt_dict['fifo_file'] = u'/tmp/%s-fiforadio' % self.username
        self.opt_dict['lirc_id'] = u'lircradio'
        self.fifo_read = None
        self.fifo_write = None
        self.ircat_pid = None

        self.dev_types = {}
        self.dev_types[0] = 'ivtv radio device'
        self.dev_types[1] = 'radio with alsa device'
        self.dev_types[2] = 'radio cabled to an audio card'
        self.opt_dict['myth_backend'] = socket.gethostname()
        self.opt_dict['radio_cardtype'] = -1
        self.opt_dict['radio_device']  = None
        self.opt_dict['radio_out'] = None
        self.opt_dict['video_device'] = None
        rfconf.check_dependencies(self.ivtv_dir)
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

        self.opt_dict['audio_card'] = rfcalls().get_alsa_cards(0)
        for m in ('Front', 'Master', 'PCM'):
            if m in rfcalls().get_alsa_mixers(0):
                self.opt_dict['audio_mixer'] = m
                break

        else:
            self.opt_dict['audio_mixer'] = rfcalls().get_alsa_mixers(0, 0)

        self.bash_commands = {}
        self.external_commands = {'test': ['echo', 'Testing the pipe\n']}

        self.__CONFIG_SECTIONS__ = { 1: u'Configuration', \
                                                            2: u'Radio Channels', \
                                                            3: u'Function Calls'}

    # end Init()

    def version(self, as_string = False):
        if as_string and self.beta:
            return u'%s Version: %s.%s.%s-beta' % (self.name, self.major, self.minor, self.patch)

        if as_string and not self.beta:
            return u'%s Version: %s.%s.%s' % (self.name, self.major, self.minor, self.patch)

        else:
            return (self.name, self.major, self.minor, self.patch, self.beta)

    # end version()

    def save_oldfile(self, file):
        """ save the old file to .old if it exists """
        try:
            os.rename(file, file + '.old')

        except Exception as e:
            pass

    # end save_old()

    def open_file(self, file_name, mode = 'rb', encoding = None, buffering = 'default'):
        """ Open a file and return a file handler if success """
        if file_name == None:
            return None

        if encoding == None:
            encoding = self.file_encoding

        if buffering == 'default':
            buffering = -1

        elif buffering == None and ('b' in mode):
            buffering = 0

        elif buffering == None and not ('b' in mode):
            buffering = 1

        try:
            if 'b' in mode:
                file_handler =  io.open(file_name, mode = mode, buffering = buffering)
            else:
                file_handler =  io.open(file_name, mode = mode, encoding = encoding, buffering = buffering)

        except IOError as e:
            if e.errno == 2:
                log('File: \"%s\" not found.\n' % file_name)
            else:
                log('File: \"%s\": %s.\n' % (file_name, e.strerror))
            return None

        return file_handler

    # end open_file ()

    def get_line(self, file, byteline, isremark = False, encoding = None):
        """
        Check line encoding and if valid return the line
        If isremark is True or False only remarks or non-remarks are returned.
        If None all are returned
        """
        if encoding == None:
            encoding = self.file_encoding

        try:
            line = byteline.decode(encoding)
            line = line.lstrip()
            line = line.replace('\n','')
            if len(line) == 0:
                return False

            if isremark == None:
                return line

            if isremark and line[0:1] == '#':
                return line

            if not isremark and not line[0:1] == '#':
                return line

        except UnicodeError:
            log('%s is not encoded in %s.\n' % (file.name, encoding))

        return False

    # end get_line()

    def check_encoding(self, file, encoding = None):
        """Check file encoding. Return True or False"""
        # regex to get the encoding string
        reconfigline = re.compile(r'#\s*(\w+):\s*(.+)')

        if encoding == None:
            encoding = self.file_encoding

        for byteline in file.readlines():
            line = self.get_line(file, byteline, True)
            if not line:
                continue

            else:
                match = reconfigline.match(line)
                if match is not None and match.group(1) == "encoding":
                    encoding = match.group(2)

                    try:
                        codecs.getencoder(encoding)

                    except LookupError:
                        log('%s has invalid encoding %s.\n' % (file.name, encoding))
                        return False

                    return True

                continue

        return False

    # end check_encoding()

    def read_commandline(self):
        """Initiate argparser and read the commandline"""

        parser = argparse.ArgumentParser(description=u'%(prog)s: ' +
                        'A daemon to play radio and process Lirc commands\n',
                        formatter_class=argparse.RawTextHelpFormatter)

        parser.add_argument('-V', '--version', action = 'store_true', default = False, dest = 'version',
                        help = 'display version')

        parser.add_argument('-D', '--description', action = 'store_true', default = False, dest = 'description',
                        help = 'prints a description in english of the program')

        parser.add_argument('-v', '--verbose', action = 'store_true', default = None, dest = 'verbose',
                        help = 'Sent log-info also to the screen.')

        parser.add_argument('-q', '--quiet', action = 'store_false', default = None, dest = 'verbose',
                        help = 'suppress all output.')

        #~ parser.add_argument('-d', '--daemon', action = 'store_true', default = None, dest = 'daemon',
                        #~ help = 'run as a daemon.')

        parser.add_argument('-c', '--configure', action = 'store_true', default = False, dest = 'configure',
                        help = 'create configfile; rename an existing file to *.old.')

        parser.add_argument('-C', '--config-file', type = str, default = None, dest = 'config_file',
                        metavar = '<file>',
                        help = 'name of the configuration file\nFalls back to \'%s%s\'\nand then        \'%s%s\'' % \
                                    (self.ivtv_dir, self.config_file, self.etc_dir, self.config_file))

        parser.add_argument('-L', '--log-file', type = str, default = None, dest = 'log_file',
                        metavar = '<file>',
                        help = 'name and path of the log file. If not writable it\nfalls back to ' +
                                    '\'%s\'\nThe directory must exist with rw permission.' % (self.log_file))

        parser.add_argument('-O', '--save-options', action = 'store_true', default = False, dest = 'save_options',
                        help = 'save the currently defined options to the config file\n' +
                                    'add options to the command-line to adjust the file.')

        parser.add_argument('-M', '--create-menu', action = 'store_true', default = False, dest = 'create_menu',
                        help = 'create a Radiomenu file %s in %s\n' % (self.myth_menu_file, self.ivtv_dir) +
                                    'with the defined channels to be used in MythTV.')

        parser.add_argument('-F', '--fifo-file', type = str, default = None, dest = 'fifo_file',
                        metavar = '<file>',
                        help = 'name of the fifo-file (%s)' % self.opt_dict['fifo_file'])

        parser.add_argument('-l', '--lirc-id', type = str, default = None, dest = 'lirc_id',
                        metavar = '<name>',
                        help = 'name of the lirc ID to respond to (%s)' % self.opt_dict['lirc_id'])

        parser.add_argument('-r', '--card-type', type = str, default = None, dest = 'radio_cardtype',
                        metavar = '<device>',
                        help = 'type of radio-device/ (%s)\n' % self.opt_dict['radio_cardtype'] +
                                    '   0 = ivtv (with /dev/video24 radio-out)\n' +
                                    '   1 = with corresponding alsa device\n' +
                                    '   2 = cabled to an audiocard\n' +
                                    '  -1 = No radiocard' )

        parser.add_argument('-R', '--radio-device', type = str, default = None, dest = 'radio_device',
                        metavar = '<device>',
                        help = 'name of the radio-device in /dev/ (%s)\n' % self.opt_dict['radio_device'] )

        parser.add_argument('-A', '--radio-out', type = str, default = None, dest = 'radio_out',
                        metavar = '<device>',
                        help = 'name of the audio-out-device in /dev/ or\n' +
                                    'the alsa device (%s)' % self.opt_dict['radio_out'])

        parser.add_argument('-T', '--video-device', type = str, default = None, dest = 'video_device',
                        metavar = '<device>',
                        help = 'name of the corresponding video-device in /dev/\n(%s)' % self.opt_dict['video_device'] )

        parser.add_argument('-B', '--myth-backend', type = str, default = None, dest = 'myth_backend',
                        metavar = '<hostname>',
                        help = 'backend dns hostname. (%s)\nSet to \'None\' string to disable checking.' % self.opt_dict['myth_backend'])

        parser.add_argument('-a', '--audio-card', type = str, default = None, dest = 'audio_card',
                        metavar = '<cardname>',
                        help = 'The audiocard name to play the radio. (%s)\n' % self.opt_dict['audio_card'])

        parser.add_argument('-m', '--audio-mixer', type = str, default = None, dest = 'audio_mixer',
                        metavar = '<mixername>',
                        help = 'The mixer name. (%s)\n' % self.opt_dict['audio_mixer'])

        # Handle the sys.exit(0) exception on --help more gracefull
        try:
            self.args = parser.parse_args()

        except:
            return(0)

    # end read_commandline()

    def read_config(self):
        """Read the configurationfile Return False on failure."""

        f = None
        for file in (self.args.config_file, self.ivtv_dir + self.config_file, self.etc_dir + self.config_file):
            if file == None or not os.access(file, os.F_OK) :
                continue

            if os.access(file, os.R_OK):
                f = self.open_file(file)
                if f != None and self.check_encoding(f):
                    break

                else:
                    log('Error opening configfile: %s\n' % file, 1)

            else:
                log('configfile: %s is not readable!\n' % file, 1 )

        if f == None:
            x = self.read_radioFrequencies_File()
            if x == False:
                log('Could not find an accessible configfile!\n', 1)

            else:
                self.write_config(True)

            return(x)

        self.args.config_file = file
        f.seek(0,0)
        type = 0
        ch_num = 0
        for byteline in f.readlines():
            try:
                line = self.get_line(f, byteline)
                if not line:
                    continue

                # Look for section headers
                config_title = re.search('\[(.*?)\]', line)
                if config_title != None and (config_title.group(1) in self.__CONFIG_SECTIONS__.values()):
                    for i, v in self.__CONFIG_SECTIONS__.items():
                        if v == config_title.group(1):
                            type = i
                            continue

                    continue

                # Unknown Section header, so ignore
                if line[0:1] == '[':
                    type = 0
                    continue

                # Read Configuration options
                elif type == 1:
                    try:
                        # Strip the name from the value
                        a = line.split('=',1)
                        # Boolean values
                        if a[0].lower().strip() in ('write_info_files', 'verbose', 'daemon'):
                            if len(a) == 1:
                                self.opt_dict[a[0].lower().strip()] = True

                            elif a[1].lower().strip() in ('true', '1', 'on' ):
                                self.opt_dict[a[0].lower().strip()] = True

                            else:
                                self.opt_dict[a[0].lower().strip()] = False

                        # Values that can be None
                        elif a[0].lower().strip() in ('radio_device', 'radio_out', 'video_device', 'myth_backend'):
                            self.opt_dict[a[0].lower().strip()] = None if (len(a) == 1 or a[1].lower().strip() == 'none') else a[1].strip()

                        elif len(a) == 2:
                            #Integer values
                            if a[0].lower().strip() in ('log_level', 'radio_cardtype'):
                                try:
                                    int(a[1])

                                except ValueError:
                                    self.opt_dict[a[0].lower().strip()] = 0

                                else:
                                    self.opt_dict[a[0].lower().strip()] = int(a[1])

                            #String values
                            else:
                                self.opt_dict[a[0].lower().strip()] = a[1].strip()

                        else:
                            log('Ignoring incomplete Options line in config file %s: %r\n' % (file, line))

                    except Exception:
                        log('Invalid Options line in config file %s: %r\n' % (file, line))
                        continue

                # Read the channel stuff
                if type == 2:
                    try:
                        # Strip the name from the frequency
                        a = line.split('=',1)
                        if len(a) != 2:
                            log('Ignoring incomplete Channel line in config file %s: %r\n' % (file, line))
                            continue

                        ch_num += 1
                        rfconf.frequencies[float(a[0].strip())] = ch_num
                        rfconf.channels[ch_num] = {}
                        rfconf.channels[ch_num]['frequency'] = float(a[0].strip())
                        rfconf.channels[ch_num]['title'] = unicode(a[1].strip())
                        if rfconf.channels[ch_num]['title'] == '':
                            rfconf.channels[ch_num]['title'] = u'Frequency %s' % a[0].strip()

                    except Exception:
                        log('Invalid Channel line in config file %s: %r\n' % (file, line))
                        continue

                # Read the lirc IDs
                if type == 3:
                    try:
                        # Strip the lircname from the command
                        a = line.split('=',1)
                        if(len(a) == 1) and (unicode(a[0].strip()) in rfconf.call_list):
                            rfconf.functioncalls[unicode(a[0].strip())] = unicode(a[0].strip())

                        elif (len(a) == 2) and (unicode(a[1].strip()) in rfconf.call_list):
                            rfconf.functioncalls[unicode(a[0].strip())] = unicode(a[1].strip())

                        elif (len(a) > 1) and unicode(a[1].strip().lower())[0:5] == 'bash:':
                            self.external_commands[unicode(a[0].strip())] = []
                            quote_cnt = 0
                            quote_cmd = ''
                            word_cmd = ''
                            aa = unicode(a[1].strip())[5:].strip()
                            for c in range(len(aa)):
                                if quote_cnt == 1:
                                    if aa[c] == '"':
                                        self.external_commands[unicode(a[0].strip())].append(quote_cmd)
                                        quote_cnt = 0
                                        quote_cmd = ''
                                        continue

                                    else:
                                        quote_cmd = u'%s%s' % (quote_cmd, aa[c])
                                        continue

                                elif quote_cnt == 0:
                                    if aa[c] == '"':
                                        quote_cnt = 1
                                        quote_cmd = ''

                                    elif aa[c] != ' ':
                                        word_cmd = u'%s%s' % (word_cmd, aa[c])
                                        continue

                                if word_cmd != '':
                                    self.external_commands[unicode(a[0].strip())].append(word_cmd)
                                    word_cmd = ''
                        elif (len(a) > 1) and unicode(a[1].strip().lower())[0:8] == 'command:':
                            bash_commands[unicode(a[0].strip())] = unicode(a[1].strip())[8:].strip()
                        else:
                            log('Ignoring Lirc line in config file %s: %r\n' % (file, line))

                    except Exception:
                        log('Invalid Lirc line in config file %s: %r\n' % (file, line))
                        continue

            except Exception as e:
                log(u'Error reading Config')
                continue

        f.close()

        #~ self.write_config(True)
        if 'log_level' in self.opt_dict.keys():
            rfconf.log_level = self.opt_dict['log_level']

        if 'log_file' in self.opt_dict.keys():
            self.log_file = self.opt_dict['log_file']

        if len(rfconf.channels) == 0:
            # There are no channels so looking for an old ~\.ivtv\radioFrequencies file
            if not self.read_radioFrequencies_File():
                # We scan for frequencies
                self.freq_list = rfcalls().detect_channels(config.opt_dict['radio_device'])
                if len(self.freq_list) == 0:
                    return False

                else:
                    ch_num = 0
                    for freq in self.freq_list:
                        ch_num += 1
                        rfconf.frequencies[freq] = ch_num
                        rfconf.channels[ch_num] = {}
                        rfconf.channels[ch_num]['frequency'] = freq
                        rfconf.channels[ch_num]['title'] = 'Channel %s' % ch_num

        return True

    # end read_config()

    def read_radioFrequencies_File(self):
        """Check for an old RadioFrequencies file."""

        if not os.access(self.ivtv_dir +  '/radioFrequencies', os.F_OK and os.R_OK) :
            self.args.config_file = None
            return False

        f = self.open_file(self.ivtv_dir +  '/radioFrequencies')
        if f == None:
            self.args.config_file = None
            return False

        f.seek(0,0)
        ch_num = 0
        for byteline in f.readlines():
            try:
                line = self.get_line(f, byteline)
                if not line:
                    continue

                # Read the channel stuff
                try:
                    # Strip the name from the frequency
                    a = re.split(';',line)
                    if len(a) != 2:
                        continue

                    ch_num += 1
                    rfconf.frequencies[float(a[1].strip())] = ch_num
                    rfconf.channels[ch_num] = {}
                    rfconf.channels[ch_num]['title'] = a[0].strip()
                    rfconf.channels[ch_num]['frequency'] = float(a[1].strip())
                    if rfconf.channels[ch_num]['title'] == '':
                        rfconf.channels[ch_num]['title'] = u'Frequency %s' % a[1].strip()

                except Exception:
                    log('Invalid line in config file %s: %r\n' % (self.ivtv_dir +  '/radioFrequencies', line))
                    continue

            except Exception as e:
                log(u'Error reading Config')
                continue

        f.close()

        if len(rfconf.channels) == 0:
            return False

        return True

    # end read_radioFrequencies_File()

    def validate_commandline(self):
        """Read the commandline and validate the values"""
        def is_video_device(path):
            if path == None or path.lower() == 'none':
                return None

            if (not os.access(path, os.F_OK and os.R_OK)):
                return False

            if ((os.major(os.stat(path).st_rdev)) != 81):
                return False

            return path

        if self.read_commandline() == 0:
             return(0)

        if self.args.version:
            print("The Netherlands (%s)" % self.version(True))
            print("The Netherlands (%s)" % rfconf.version(True))
            return(0)

        if self.args.description:
            print("The Netherlands (%s)" % self.version(True))
            print("The Netherlands (%s)" % rfconf.version(True))
            print(description_text)
            return(0)

        conf_read = self.read_config()
        if self.args.verbose != None:
            self.opt_dict['verbose'] = self.args.verbose
            rfconf.opt_dict['verbose'] = self.opt_dict['verbose']

        # Opening the logfile
        if self.args.log_file != None:
            rfconf.log_output = self.open_file(self.args.log_file, mode = 'ab')

        if rfconf.log_output != None:
            rfconf.log_file = self.args.log_file
            sys.stderr = rfconf.log_output

        else:
            rfconf.log_output = self.open_file(self.log_file, mode = 'ab')
            if rfconf.log_output != None:
                rfconf.log_file = self.log_file
                sys.stderr = rfconf.log_output

        if self.args.log_file != None and not os.access(self.args.log_file, os.W_OK):
            log('Error opening supplied logfile: %s. \nCheck permissions! Falling back to %s\n' % (self.args.log_file, self.log_file), 0)

        if self.args.fifo_file != None:
            self.opt_dict['fifo_file'] = self.args.fifo_file

        if self.args.lirc_id != None:
            self.opt_dict['lirc_id'] = self.args.lirc_id

        if self.args.myth_backend != None:
            self.opt_dict['myth_backend'] = self.args.myth_backend

        if self.opt_dict['myth_backend'] == None:
            self.opt_dict['myth_backend'] = socket.gethostname()

        elif self.opt_dict['myth_backend'].lower().strip() == 'none':
            self.opt_dict['myth_backend'] = None

        if self.opt_dict['myth_backend'] != None and rfcalls().query_backend(self.opt_dict['myth_backend']) == -2:
            log('The MythTV backend %s is not responding!\n' % self.opt_dict['myth_backend'],1)
            log('Run with --myth-backend None to disable checking!\n', 0)

        if self.args.radio_cardtype != None:
            self.opt_dict['radio_cardtype'] = self.args.radio_cardtype

        if self.opt_dict['radio_cardtype'] != None and 0 <= self.opt_dict['radio_cardtype'] <= 2:
            if self.args.radio_device != None:
                x = is_video_device(self.args.radio_device)
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
                udevpath =  rfcalls().query_udev_path( self.opt_dict['radio_device'], 'video4linux')
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
            if self.args.video_device != None:
                self.opt_dict['video_device'] = self.args.video_device

            udevpath =  rfcalls().query_udev_path( self.opt_dict['video_device'], 'video4linux')
            if autodetect_card['udevpath'] != udevpath:
                log('%s is not the corresponding video device. Setting to %s\n' % (self.opt_dict['video_device'], autodetect_card['video_device']))
                self.opt_dict['video_device'] = autodetect_card['video_device']

            if self.args.radio_out != None:
                self.opt_dict['radio_out'] = self.args.radio_out

            if self.opt_dict['radio_cardtype'] == 0:
                udevpath =  rfcalls().query_udev_path( self.opt_dict['radio_out'], 'video4linux')
                if autodetect_card['udevpath'] != udevpath:
                    log('%s is not the corresponding radio-out device. Setting to %s\n' % (self.opt_dict['radio_out'], autodetect_card['radio_out']))
                    self.opt_dict['radio_out'] = autodetect_card['radio_out']

            elif self.opt_dict['radio_cardtype'] == 1:
                if autodetect_card['radio_out'] != self.opt_dict['radio_out']:
                    log('%s is not the corresponding alsa device. Setting to %s\n' % (self.opt_dict['radio_out'], autodetect_card['radio_out']))
                    self.opt_dict['radio_out'] = autodetect_card['radio_out']

            else:
                if not self.opt_dict['radio_out'] in rfcalls().get_alsa_cards():
                    log('%s is not a recognized audiocard. Disabling radio\n' % (self.opt_dict['radio_out']), 1)
                    self.opt_dict['radio_cardtype'] = None
                    self.opt_dict['radio_device'] = None
                    self.opt_dict['video_device'] = None
                    self.opt_dict['radio_out'] = None

        else:
            self.opt_dict['radio_cardtype'] = -1
            self.opt_dict['radio_device']  = None
            self.opt_dict['radio_out'] = None
            self.opt_dict['video_device'] = None

        if self.args.audio_card != None:
            if self.args.audio_card in rfcalls().get_alsa_cards():
                self.opt_dict['audio_card'] = self.args.audio_card

            else:
                log('%s is not a recognized audiocard\n' % self.args.audio_card, 1)

        if not self.opt_dict['audio_card'] in rfcalls().get_alsa_cards():
            log('%s is not a recognized audiocard\n' % self.opt_dict['audio_card'], 1)
            self.opt_dict['audio_card'] = rfcalls().get_alsa_cards(0)

        cardid = rfcalls().get_cardid(self.opt_dict['audio_card'])

        if self.args.audio_mixer != None:
            if self.args.audio_mixer in rfcalls().get_alsa_mixers(cardid):
                self.opt_dict['audio_mixer'] = self.args.audio_mixer

            else:
                log('%s is not a recognized audiomixer]n' % self.args.audio_mixer, 1)

        if not self.opt_dict['audio_mixer'] in rfcalls().get_alsa_mixers(cardid):
            log('%s is not a recognized audiomixer\n' % self.opt_dict['audio_mixer'], 1)
            self.opt_dict['audio_card'] = rfcalls().get_alsa_mixers(cardid, 0)


        #~ self.opt_dict['aplay_pcm']

        self.write_opts_to_log()
        if self.args.configure:
            if self.opt_dict['radio_device'] == None:
                log('You need an accesible radio-device to configure\n')
                self.write_config(False)
                return(1)
            else:
                self.write_config(True)
                return(0)

        if self.args.save_options:
            self.write_config(False)
            return(0)

        if len(rfconf.channels) == 0 and self.opt_dict['radio_device'] != None:
            log('There are no channels defined! Exiting!\n', 0)
            log('Run with --card-type -1 to disable radio support!\n', 0)
            log('or with --configure to probe for available frequencies!\n', 0)
            return(1)

        rfconf.opt_dict = self.opt_dict
        if self.opt_dict['radio_cardtype'] != None and 0 <= self.opt_dict['radio_cardtype'] <= 2:
            if not rfconf.set_mixer():
                log('Error setting the mixer\n')
                return(1)

    # end validate_commandline()

    def validate_config(self):
        if len(self.radio_devs) == 0:
            print 'No radio devices found!\n'

        elif len(self.radio_devs) == 1:
            print 'Only one radio devices found of type %s!\n' % self.dev_types[self.radio_devs[0]['radio_cardtype']]

        else:
            print 'Select the radio device to use:\n'
            for i in range(len(self.radio_devs)):
                print

    # end validate_config()

    def open_fifo_filehandles(self):
        # Checking out the fifo file
        try:
            tmpval = os.umask(0115)
            for f in (self.opt_dict['fifo_file'],):
                if os.access(f, os.F_OK):
                    if not S_ISFIFO(os.stat(f).st_mode):
                         os.remove(f)
                         os.mkfifo(f, 0662)

                    if not os.access(f, os.R_OK):
                        os.chmod(f, 0662)

                else:
                    os.mkfifo(f, 0662)

        except:
            log('Error creating fifo-file: %s\n' % self.opt_dict['fifo_file'],0)

        os.umask(tmpval)

        # Opening the read handle to the fifo
        try:
            self.fifo_read = config.open_file(self.opt_dict['fifo_file'], mode = 'rb', buffering = None)

        except:
            log('Error reading fifo-file: %s\n' % self.opt_dict['fifo_file'],0)
            return(1)

        # Opening the write handle to the fifo
        try:
            self.fifo_write = config.open_file(self.opt_dict['fifo_file'], mode = 'wb', buffering = None)

        except:
            log('Error writing to fifo-file: %s\n' % self.opt_dict['fifo_file'],0)
            return(1)
    # end open_fifo_filehandles()

    def start_ircat(self):
        if call(['pgrep', 'lircd']) != 0:
            log('No lirc daemon found, so not starting ircat\n', 1)

        else:
            self.ircat_pid = Popen(["/usr/bin/ircat", self.opt_dict['lirc_id']], stdout = self.fifo_write, stderr = rfconf.log_output)

    # end start_ircat()

    def detect_radiodevice(self):
        video_devs = []
        for f in os.listdir('/dev/'):
            if f[:5] == 'video':
                video_devs.append(f)

        audio_cards = {}
        for id in range(len(rfcalls().get_alsa_cards())):
            audio_cards[id] = rfcalls().query_udev_path(u'/dev/snd/controlC%s' % id, 'sound')

        self.radio_devs = []
        for f in os.listdir('/dev/'):
            if f[:5] == 'radio':
                devno = int(f[5:])
                radio_card = {}
                radio_card['radio_device'] = u'/dev/%s' % f
                radio_card['udevpath'] = rfcalls().query_udev_path('/dev/%s' % f, 'video4linux')
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

                for id in range(len(rfcalls().get_alsa_cards())):
                    if audio_cards[id] == radio_card['udevpath']:
                        radio_card['radio_out'] = rfcalls().get_alsa_cards(id)
                        radio_card['radio_cardtype'] = 1
                        break

                else:
                    radio_card['radio_out'] = None
                    radio_card['radio_cardtype'] = 2

                self.radio_devs.append(radio_card)

    # end detect_radiodevice()

    def write_opts_to_log(self):
        """
        Save the the used options to the logfile
        """
        if rfconf.log_output == None:
            return(0)

        log(u'',1, 2)
        log(u'Starting lircradio',1, 2)
        log(u'Python versie: %s.%s.%s' % (sys.version_info[0], sys.version_info[1], sys.version_info[2]),1, 2)
        log(u'The Netherlands (%s)' % self.version(True), 1, 2)
        log(u'The Netherlands (%s)' % rfconf.version(True), 1, 2)
        log(u'log level = %s' % (rfconf.log_level), 1, 2)
        log(u'config_file = %s' % (self.args.config_file), 1, 2)
        log(u'verbose = %s\n' % self.opt_dict['verbose'], 1, 2)
        log(u'fifo_file = %s\n' % self.opt_dict['fifo_file'], 1, 2)
        log(u'lirc_id = %s\n' % self.opt_dict['lirc_id'], 1, 2)
        log(u'radio_cardtype = %s\n' % self.opt_dict['radio_cardtype'], 1, 2)
        log(u'radio_device = %s\n' % self.opt_dict['radio_device'], 1, 2)
        log(u'radio_out = %s\n' % self.opt_dict['radio_out'], 1, 2)
        log(u'video_device = %s\n' % self.opt_dict['video_device'], 1, 2)
        log(u'myth_backend = %s\n' % self.opt_dict['myth_backend'], 1, 2)
        log(u'audio_card = %s\n' % self.opt_dict['audio_card'], 1, 2)
        log(u'audio_mixer = %s\n' % self.opt_dict['audio_mixer'], 1, 2)
        log(u'',1, 2)

    # end write_opts_to_log()

    def write_config(self, add_channels = None):
        """
        Save the channel info and the default options
        if add_channels is False or None we copy over the Channels sections
        If add_channels is None we convert the channel info to the new form
        if add_channels is True we create a fresh channels section
        """
        if self.args.config_file == None:
            self.args.config_file = self.ivtv_dir + self.config_file

        self.save_oldfile(self.args.config_file)
        f = self.open_file(self.args.config_file, 'w')
        if f == None:
            return False

        f.write(u'# encoding: utf-8\n')
        f.write(u'\n')

        # Save the options
        f.write(u'# This is a list with default options set by the --save-options (-O)\n')
        f.write(u'# argument. They can be overruled on the commandline.\n')
        f.write(u'# Be carefull with manually editing. Invalid options will be\n')
        f.write(u'# silently ignored.\n')
        f.write(u'# To edit you beter run --save-options with all the desired defaults.\n')
        f.write(u'# Options not shown here can not be set this way.\n')
        f.write(u'\n')
        f.write(u'[%s]\n' % self.__CONFIG_SECTIONS__[1])
        if self.write_info_files:
            f.write(u'write_info_files = True\n')
            f.write(u'\n')

        f.write(u'# This handles what goes to the log and screen\n')
        f.write(u'#  0 = Nothing (use quiet/verbose mode to turns off/on screen output,\n')
        f.write(u'#      but keep a log)\n')
        f.write(u'#  1 = Log System Actions and errors\n')
        f.write(u'#  2 = Log all commands coming through the pipe, Mainly for debugging\n')
        f.write(u'#  4 = log unknown commands coming through the pipe\n')
        f.write(u'#  8 = log Channel changes\n')
        f.write(u'# 16 = log Volume changes\n')
        f.write(u'# 32 = log all radiofunction calls, Mainly for debugging\n')
        f.write(u'log_file = %s\n' % rfconf.log_file)
        f.write(u'log_level = %s\n' % rfconf.log_level)
        f.write(u'verbose = %s\n' % self.opt_dict['verbose'])
        f.write(u'\n')
        f.write(u'fifo_file = %s\n' % self.opt_dict['fifo_file'])
        f.write(u'lirc_id = %s\n' % self.opt_dict['lirc_id'])
        f.write(u'\n')
        f.write(u'# radio_cardtype can be any of four values \n')
        f.write(u'# 0 = ivtv (with /dev/video24 as radio-out)\n')
        f.write(u'# 1 = with corresponding alsa device as radio-out\n')
        f.write(u'# 2 = cabled to an audiocard set in radio-out\n')
        f.write(u'# -1 = No radiocard\n')
        f.write(u'# All but the audiocard for type 2 will be autodetected\n')
        f.write(u'# It will default to the first detected ivtv-card or else any other.\n')
        f.write(u'radio_cardtype = %s\n' % self.opt_dict['radio_cardtype'])
        f.write(u'radio_device = %s\n' % self.opt_dict['radio_device'])
        f.write(u'radio_out = %s\n' % self.opt_dict['radio_out'])
        f.write(u'video_device = %s\n' % self.opt_dict['video_device'])
        f.write(u'myth_backend = %s\n' % self.opt_dict['myth_backend'])
        f.write(u'audio_card = %s\n' % self.opt_dict['audio_card'])
        f.write(u'audio_mixer = %s\n' % self.opt_dict['audio_mixer'])
        #f.write(u' = %s\n' % self.opt_dict[''])
        f.write(u'\n')

        f.write(u'# These are the channels to use. You can disable a channel by placing\n')
        f.write(u'# a \'#\' in front. You can change the names to suit your own preferences.\n')
        f.write(u'# Place them in the order you want them numbered.\n')
        f.write(u'\n')
        f.write(u'[%s]\n' % self.__CONFIG_SECTIONS__[2])

        if add_channels != True:
            # just copy over the channels section
            fo = self.open_file(self.args.config_file + '.old')
            if fo == None or not self.check_encoding(fo):
                # We cannot read the old config, so we create a new one
                log('Error Opening the old config. Trying for an old radioFrequencies file.\n')
                x = self.read_radioFrequencies_File()
                if x == False:
                    log('Error Opening an old radioFrequencies file. Creating a new Channellist.\n')

                add_channels = True

            else:
                add_channels = False

            if add_channels != True:
                fo.seek(0,0)
                type = 0
                if add_channels == None:
                    # it's an old type config without sections
                    type = 2

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

                        if type > 1:
                            # We just copy everything except the old configuration (type = 1)
                            f.write(line + u'\n')
                    except:
                        log('Error reading old config\n')
                        continue

                fo.close()
                f.close()
                return True

        if add_channels:
            self.freq_list = rfcalls().detect_channels(config.opt_dict['radio_device'])
            ch_num = 0
            for c in rfconf.channels.itervalues():
                ch_num += 1
                if c['frequency'] in self.freq_list:
                    f.write(u'%s = %s\n' % (c['frequency'], c['title']))
                    self.freq_list.remove(c['frequency'])

                else:
                    for i in (0.1, -0.1, 0.2, -0.2):
                        if c['frequency'] + i in self.freq_list:
                            f.write(u'%s = %s\n' % (c['frequency'] + i, c['title']))
                            self.freq_list.remove(c['frequency'] + i)
                            break

                    else:
                        f.write(u'# Not detected frequency: %s = %s\n' % (c['frequency'], c['title']))

            for freq in self.freq_list:
                ch_num += 1
                f.write(u'%s = Channel %s\n' % (freq, ch_num))

        f.write(u'\n')
        f.write(u'# These are the commands to listen to. You have to put them in your\n')
        f.write(u'# .lircrc file like:\n')
        f.write(u'# begin\n')
        f.write(u'#     prog = mythradio\n')
        f.write(u'#     button = KEY_POWER2\n')
        f.write(u'#     repeat = 0\n')
        f.write(u'#     config = suspend\n')
        f.write(u'# end\n')
        f.write(u'# In here it goes like:\n')
        f.write(u'# <lirc/fifo-command> = <internal-command>\n')
        f.write(u'# suspend = Suspend\n')
        f.write(u'# or if they are equal just\n')
        f.write(u'# Suspend\n')
        f.write(u'\n')
        f.write(u'# Available internal commands are: PowerOff, Reboot, Hibernate, Suspend\n')
        f.write(u'#   PlayRadio, StopRadio, ToggleStartStop, ChannelUp, ChannelDown, \n')
        f.write(u'#   VolumeUp, VolumeDown, Mute, CreateMythfmMenu \n')
        f.write(u'# The first four are handled in the bash script: `~/.ivtv/Commands.sh`\n')
        f.write(u'# You can also move that script for global access to `/usr/bin`\n')
        f.write(u'# Numerical commands you can not set here, they are always translated to\n')
        f.write(u'# a channelchange.\n')
        f.write(u'\n')
        f.write(u'# You can add command sequences to `~/.ivtv/Commands.sh`. You then\n')
        f.write(u'# precede the command with COMMAND: \n')
        f.write(u'# <lirc/fifo-command> = COMMAND:<~/.ivtv/Commands.sh-command>\n')
        f.write(u'# test = COMMAND:suspend\n')
        f.write(u'# The example will call the suspend command in there and is the same as: \n')
        f.write(u'# test = Suspend\n')
        f.write(u'\n')
        f.write(u'# You can also specify an external command or script by preceding the\n')
        f.write(u'# command with BASH: You best supply a full path.\n')
        f.write(u'# <lirc/fifo-command> = BASH:<external-command>\n')
        f.write(u'# test = BASH:echo "Testing the pipe"\n')
        f.write(u'# Quotes are only needed if required by the command itself and then only\n')
        f.write(u'# use double quotes\n')
        f.write(u'\n')
        f.write(u'# You can link a command to multiple lirc/fifo commands\n')
        f.write(u'# If you use a lirc/fifo commands more then ones the last is used\n')
        f.write(u'# If one is internal and an other external, the last internal is used\n')
        f.write(u'# \n')
        f.write(u'[%s]\n' % self.__CONFIG_SECTIONS__[3])
        for c, command in rfconf.functioncalls.items():
            f.write(u'%s = %s\n' % (c, command))

        for c, command in self.bash_commands.items():
            f.write(u'%s = COMMAND:%s\n' % (c, command))

        for c, command in self.external_commands.items():
            line = u'%s = BASH:' % c
            for cc in command:
                if ' ' in cc:
                    line = u'%s "%s"' % (line, cc)

                else:
                    line = u'%s %s' % (line, cc)

            line = re.sub('\n', '', line)
            f.write(line)

        f.close()
        return True

    # end write_config()

    def close(self):
        # close everything neatly
        if self.ircat_pid != None:
            self.ircat_pid.kill()

        if self.fifo_read != None:
            self.fifo_read.close()

        if self.fifo_write != None:
             self.fifo_write.close()

        if os.access(self.opt_dict['fifo_file'], os.F_OK):
            os.remove(self.opt_dict['fifo_file'])

        rfconf.close()

    # end close()

# end Configure
config = Configure()

class Listen_To(Thread):
    """
    Listening Thread to the fifo pipe
    """
    def __init__(self, fifo):
        Thread.__init__(self)
        self.quit = False
        self.fifo = fifo

    def run(self):
        byteline = ''
        try:
            while True:
                byte = self.fifo.readline(1)
                if self.quit:
                    return(0)

                if byte == None or (byte == '\n' and byteline == '') or (byte == ' ' and byteline == ''):
                    continue

                elif byte != '\n':
                    byteline += byte
                    continue

                elif byteline.strip().lower() == 'start':
                    log('Starting FiFo Listener on %s\n'% config.opt_dict['fifo_file'], 1)
                    byteline = ''
                    continue

                elif byteline.strip().lower() == 'quit' or self.quit:
                    log('%s command received.' % byteline, 2)
                    return(0)

                elif re.match('([0-9]+?)', byteline.strip()):
                    log('%s command received.' % byteline, 2)
                    rfcalls().select_channel(int(re.match('([0-9]+?)', byteline.strip()).group(0)))
                    byteline = ''

                elif byteline.strip() in rfconf.functioncalls.keys():
                    log('%s command received.' % byteline, 2)
                    rfcalls().rf_function_call(rfconf.functioncalls[byteline.strip()])
                    byteline = ''

                elif byteline.strip() in config.bash_commands.keys():
                    log('%s command received.' % byteline, 2)
                    rfcalls().rf_function_call('Command', rfconf.functioncalls[byteline.strip()])
                    byteline = ''

                elif byteline.strip() in config.external_commands.keys():
                    log('%s command received.' % byteline, 2)
                    call(config.external_commands[byteline.strip()])
                    byteline = ''

                else:
                    log('Unregognized %s command received.' % byteline, 4)
                    byteline = ''

        except:
            err_obj = sys.exc_info()[2]
            log('\nAn unexpected error has occured at line: %s, %s: %s\n' %  (err_obj.tb_lineno, err_obj.tb_lasti, sys.exc_info()[1]), 0)

            while True:
                err_obj = err_obj.tb_next
                if err_obj == None:
                    break

                log('                   tracing back to line: %s, %s\n' %  (err_obj.tb_lineno, err_obj.tb_lasti), 0)

            log('\nIf you want assistence, please attach your configuration and log files!\n     %s\n     %s\n' % (config.config_file, config.log_file),0)
            return(99)

# end Listen_To()

def main():
    # We want to handle unexpected errors nicely. With a message to the log
    try:
        # Get the options, channels and other configuration

        x = config.validate_commandline()
        if x != None:
            return(x)

        log( 'Starting Lirc Listener on %s\n'% config.opt_dict['lirc_id'], 0)
        log( 'To QUIT: echo "quit" to %s\n'% config.opt_dict['fifo_file'], 0, 1)
        #~ print rfconf.channels
        config.open_fifo_filehandles()
        config.start_ircat()

        listener = Listen_To(config.fifo_read)
        listener.start()

        listener.join()
        log( 'Closing down\n',1)
        if config.ircat_pid != None:
            config.ircat_pid.kill()

    except:
        err_obj = sys.exc_info()[2]
        log('\nAn unexpected error has occured at line: %s, %s: %s\n' %  (err_obj.tb_lineno, err_obj.tb_lasti, sys.exc_info()[1]), 0)

        while True:
            err_obj = err_obj.tb_next
            if err_obj == None:
                break

            log('                   tracing back to line: %s, %s\n' %  (err_obj.tb_lineno, err_obj.tb_lasti), 0)

        log('\nIf you want assistence, please attach your configuration and log files!\n     %s\n     %s\n' % (config.config_file, config.log_file),0)
        return(99)

    # and return success
    return(0)
# end main()

# allow this to be a module
if __name__ == '__main__':
    x = main()
    config.close()
    sys.exit(x)
