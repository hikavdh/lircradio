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

import sys, io, os, datetime, time
import re, codecs, locale, pwd
import socket, argparse, traceback
from stat import *
from threading import Thread
from Queue import Queue
try:
    from subprocess32 import *
except:
    from subprocess import *

# check Python version
if sys.version_info[:2] < (2,6):
    sys.stderr.write("lircradio requires Pyton 2.6 or higher\n")
    sys.exit(2)

elif sys.version_info[:2] >= (3,0):
    sys.stderr.write("lircradio does not support Pyton 3 or higher.\nExpect errors while we proceed\n")

class Logging(Thread):
    def __init__(self):
        Thread.__init__(self)
        self.log_level = 29
        self.verbose = True
        self.log_queue = Queue()
        self.log_output = None
        self.stderr_write = None
        self.stderr_read = None
        self.stderr_fifo = None
        self.stderr_listner = None

    def run(self):
        self.log_queue.put(u'Opening Logfile: %s\n' % config.log_file)
        self.log_output = config.open_file(config.log_file, mode = 'ab')
        for p in range(config.plugin_count):
            config.pi_conf[p].log_queue = self.log_queue
            config.pi_conf[p].stderr_write = self.stderr_write

        try:
            while True:
                try:
                    if self.log_queue != None:
                        byteline = self.log_queue.get()
                        if isinstance(byteline, (str,unicode)):
                            if byteline == 'quit':
                                return(0)

                            self.log(byteline)

                        elif isinstance(byteline, (list,tuple)):
                            if len(byteline) == 1:
                                self.log(byteline[0])

                            elif len(byteline) == 2:
                                self.log(byteline[0], byteline[1])

                            elif len(byteline) > 2:
                                self.writelog(byteline[0], byteline[1], byteline[2])

                except:
                    pass

                self.rotate_log()

        except:
            self.log('\nAn unexpected error has occured:\n', 0)
            self.log(traceback.format_exc())
            self.log('\nIf you want assistence, please attach your configuration and log files!\n     %s\n     %s\n' % (config.config_file, config.log_file),0)
            return(99)

    def log(self, message, log_level = 1, log_target = 3):
        self.log_queue.put([message, log_level, log_target])

    def writelog(self, message, log_level = 1, log_target = 3):
        """
        Log messages to log and/or screen
        """
        def now():
             return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z') + ': '

        if type(message) != unicode:
            message = unicode(message)

        # Log to the screen
        if log_level == 0 or ((self.verbose) and (log_level & self.log_level) and (log_target & 1)):
            sys.stdout.write(message.encode("utf-8"))

        # Log to the log-file
        if (log_level == 0 or ((log_level & self.log_level) and (log_target & 2))) and self.log_output != None:
            message = u'%s%s\n' % (now(), message.replace('\n',''))
            self.log_output.write(message.encode("utf-8"))

    def rotate_log(self):
        if  self.log_output == None or config.log_file == '':
            return

        self.log_output.flush()
        if os.stat(config.log_file).st_size < config.max_logsize:
            return

        self.log_output.close()
        if os.access('%s.%s' % (config.log_file, config.max_logcount), os.F_OK):
            os.remove('%s.%s' % (config.log_file, config.max_logcount))

        for i in range(self.max_logcount - 1, 0, -1):
            if os.access('%s.%s' % (config.log_file, i), os.F_OK):
                os.rename('%s.%s' % (config.log_file, i), '%s.%s' % (config.log_file, i + 1))

        os.rename(config.log_file, '%s.1' % (config.log_file))

        self.log_output =  config.open_file(config.log_file, mode = 'ab')

    def open_stderr_filehandles(self):
        self.stderr_fifo = '/tmp/lircradio_stderr_fifo'
        self.stderr_listner = Listen_to_StdErr()
        x = FiFo_Activator(self.stderr_fifo, 'stderr')
        x.start()
        self.stderr_listner.start()

        # Opening the read handle to the fifo
        try:
            self.stderr_read = io.FileIO(self.stderr_fifo, mode = 'r')

        except:
            self.log('Error reading stderr_fifo: %s\n' % (self.stderr_fifo),0)
            self.log(traceback.format_exc())
            return(1)

        # Opening the write handle to the fifo
        try:
            self.stderr_write =  io.FileIO(self.stderr_fifo, mode = 'w')

        except:
            self.log('Error writing to stderr_fifo: %s\n' % self.stderr_fifo, 0)
            self.log(traceback.format_exc())
            return(1)

# end Logging()
log = Logging()

class Configure:
    """This class holds all configuration details and manages file IO"""

    def __init__(self):

        self.name ='lircradio.py'
        self.major = 0
        self.minor = 3
        self.patch = 0
        self.beta = True

        self.write_info_files = False
        #  1=Log System Actions and errors
        #  2=Log all commands coming through the pipe, Mainly for debugging
        #  4=log unknown commands coming through the pipe
        #  8=log Channel changes
        # 16=log Volume changes
        # 32=log all radiofunction calls, Mainly for debugging
        log.log_level = 29
        self.max_logsize = 1048576
        self.max_logcount = 5

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
            log.log('Creating %s directory,\n' % self.ivtv_dir)
            os.mkdir(self.ivtv_dir)

        self.etc_dir = u'/etc/lircradio'
        self.config_file =u'/lircradio.conf'
        self.log_file = u'%s/lircradio.log' % self.ivtv_dir
        self.opt_dict['verbose'] = False
        self.opt_dict['case_sensitive'] = False

        # Initialising fifo variables
        self.opt_dict['fifo_file'] = u'/tmp/%s-fiforadio' % self.username
        self.opt_dict['lirc_id'] = u'lircradio'
        self.fifo_read = None
        self.fifo_write = None
        self.ircat_pid = None
        self.check_commands_sh()
        self.functioncalls = {u'poweroff'                  :u'PowerOff',
                                         u'reboot'                      :u'Reboot',
                                         u'hibernate'                :u'Hibernate',
                                         u'suspend'                    :u'Suspend'}
        self.call_list = {}
        #~ self.call_list_lower = {}
        for v in self.functioncalls.values():
            self.call_list[v.lower()] = {}
            self.call_list[v.lower()]['plugin'] = -1
            self.call_list[v.lower()]['function'] = v
            #~ self.call_list[v.lower()] = -1
            #~ self.call_list_lower[v.lower()] = -1

        self.function_commands = {}
        self.external_commands = {}
        self.external_commands_lower = {}
        self.shell_commands = {'test': ['echo', 'Testing the pipe\n']}
        self.shell_commands_lower = {'test': ['echo', 'Testing the pipe\n']}
        self.plugin_list = {0:'testPlugin',
                                     1:'radioFunctions'}

        self.__CONFIG_SECTIONS__ = {-1: {1: u'Configuration', 2: u'Function Calls'}}
        self.__BOOL_VARS__ = ['write_info_files', 'verbose', 'case_sensitive']
        self.__INT_VARS__ = ['log_level']
        self.__STR_VARS__ = ['log_file', 'fifo_file', 'lirc_id']
        self.__NONE_STR_VARS__ = []

        self.get_plugins()

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
        if os.path.exists(file):
            os.rename(file, file + '.old')

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
                log.log('File: \"%s\" not found.\n' % file_name)
            else:
                log.log('File: \"%s\": %s.\n' % (file_name, e.strerror))
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
            log.log('%s is not encoded in %s.\n' % (file.name, encoding))

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
                        log.log('%s has invalid encoding %s.\n' % (file.name, encoding))
                        return False

                    return True

                continue

        return False

    # end check_encoding()

    def check_commands_sh(self):
        poweroff = self.check_path("poweroff", True)
        reboot = self.check_path("reboot", True)
        hibernate_ram = self.check_path("hibernate-ram", True)
        hibernate = self.check_path("hibernate", True)
        pm_suspend = self.check_path("pm-suspend", True)
        pm_hibernate =self.check_path("pm-hibernate", True)

        # Checking for the presence of Commands.sh
        if os.access(self.ivtv_dir + '/Commands.sh', os.F_OK):
            if not os.access(self.ivtv_dir + '/Commands.sh', os.X_OK):
                os.chmod(self.ivtv_dir + '/Commands.sh', 0750)

            self.command_name = self.ivtv_dir + '/Commands.sh'

        elif os.access('/usr/bin/Commands.sh', os.X_OK):
            self.command_name = '/usr/bin/Commands.sh'

        else:
            f = self.open_file(self.ivtv_dir + '/Commands.sh', 'wb')
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

    # end check_commands_sh()

    def check_path(self, name, use_sudo = False):
        if use_sudo:
            try:
                path = check_output(['sudo', 'which', name], stderr = None)
                return re.sub('\n', '',path)

            except:
                log.log('%s not Found!\n' % (name))
                return None

        else:
            try:
                path = check_output(['which', name], stderr = None)
                return re.sub('\n', '',path)

            except:
                log.log('%s not Found!\n' % (name))
                return None

    # end check_path()

    def get_plugins(self):
        self.plugins = []
        self.pi_conf = {}
        self.pi_func = {}
        f = self.open_file('%s/include' % (self.etc_dir))
        if f == None:
            return

        pi_cnt = 0
        for byteline in f.readlines():
            line = self.get_line(f, byteline)
            if not line:
                continue

            a = line.split(';')
            if len(a) != 2:
                continue

            try:
                if a[0] in self.plugin_list.values() and not a[0] in self.plugins:
                    if a[0] == self.plugin_list[1]:
                        self.plugins.append(a[0])
                        from radioFunctions import config as piconf
                        self.pi_conf[pi_cnt] = piconf
                        from radioFunctions import RadioFunctions
                        self.pi_func[pi_cnt] = RadioFunctions

                    pi_cnt += 1

            except:
                print "Unable to load %s.py. Make sure it's in the same directory!\n" % self.plugins[pi_cnt]
                traceback.format_exc()

        self.plugin_count = pi_cnt
        for p in range(self.plugin_count):
            self.pi_conf[p].log_queue = None
            self.pi_conf[p].stderr_write = None
            self.pi_conf[p].init_plugin(self.ivtv_dir, self.plugins)
            self.__CONFIG_SECTIONS__ [p] = self.pi_conf[p].__CONFIG_SECTIONS__
            self.__BOOL_VARS__.extend(self.pi_conf[p].__BOOL_VARS__)
            self.__INT_VARS__.extend(self.pi_conf[p].__INT_VARS__)
            self.__STR_VARS__.extend(self.pi_conf[p].__STR_VARS__)
            self.__NONE_STR_VARS__.extend(self.pi_conf[p].__NONE_STR_VARS__)
            for v in self.pi_conf[p].functioncalls.values():
                if v.lower() in self.call_list.keys():
                    continue

                self.call_list[v.lower()] = {}
                self.call_list[v.lower()]['plugin'] = p
                self.call_list[v.lower()]['function'] = v

    # end get_plugins()

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

        parser.add_argument('-F', '--fifo-file', type = str, default = None, dest = 'fifo_file',
                        metavar = '<file>',
                        help = 'name of the fifo-file (%s)' % self.opt_dict['fifo_file'])

        parser.add_argument('-l', '--lirc-id', type = str, default = None, dest = 'lirc_id',
                        metavar = '<name>',
                        help = 'name of the lirc ID to respond to (%s)' % self.opt_dict['lirc_id'])

        parser.add_argument('-s', '--case-sensitive', action = 'store_true', default = None, dest = 'case_sensitive',
                        help = 'Make all commands case sensitive.')

        #~ parser.add_argument('-d', '--daemon', action = 'store_true', default = None, dest = 'daemon',
                        #~ help = 'run as a daemon.')

        for p in range(self.plugin_count):
            parser = self.pi_conf[p].init_parser(parser)

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
                    log.log('Error opening configfile: %s\n' % file, 1)

            else:
                log.log('configfile: %s is not readable!\n' % file, 1 )

        if f == None:
            log.log('Could not find an accessible configfile!\n', 1)
            return(x)

        self.args.config_file = file
        f.seek(0,0)
        type = 0
        plugin = -1
        ch_num = 0
        for byteline in f.readlines():
            try:
                line = self.get_line(f, byteline)
                if not line:
                    continue

                # Look for section headers
                config_title = re.search('\[(.*?)\]', line)
                if config_title != None:
                    for p in range(-1, self.plugin_count):
                        for i, v in self.__CONFIG_SECTIONS__[p].items():
                            if v == config_title.group(1):
                                type = i
                                plugin = p
                                break

                    continue

                # Unknown Section header, so ignore
                if line[0:1] == '[':
                    type = 0
                    continue

                # Read Configuration options
                elif plugin == -1:
                    if type == 1:
                        try:
                            # Strip the name from the value
                            a = line.split('=',1)
                            # Boolean values
                            if a[0].lower().strip() in self.__BOOL_VARS__:
                                if len(a) == 1:
                                    self.opt_dict[a[0].lower().strip()] = True

                                elif a[1].lower().strip() in ('true', '1', 'on' ):
                                    self.opt_dict[a[0].lower().strip()] = True

                                else:
                                    self.opt_dict[a[0].lower().strip()] = False

                            # Values that can be None
                            elif a[0].lower().strip() in self.__NONE_STR_VARS__:
                                self.opt_dict[a[0].lower().strip()] = None if (len(a) == 1 or a[1].lower().strip() == 'none') else a[1].strip()

                            elif len(a) == 2:
                                #Integer values
                                if a[0].lower().strip() in self.__INT_VARS__:
                                    try:
                                        int(a[1])

                                    except ValueError:
                                        self.opt_dict[a[0].lower().strip()] = 0

                                    else:
                                        self.opt_dict[a[0].lower().strip()] = int(a[1])

                                #String values
                                elif a[0].lower().strip() in self.__STR_VARS__:
                                    self.opt_dict[a[0].lower().strip()] = a[1].strip()

                                else:
                                    log.log('Ignoring Options line in config file %s: %r\n' % (file, line))

                            else:
                                log.log('Ignoring incomplete Options line in config file %s: %r\n' % (file, line))

                        except:
                            log.log('Invalid Options line in config file %s: %r\n' % (file, line))
                            continue

                    # Read the lirc IDs
                    if type == 2:
                        try:
                            # Strip the lircname from the command
                            a = line.split('=',1)
                            lirc_cmd = unicode(a[0].strip())
                            cmd_line = lirc_cmd
                            if len(a) > 1:
                                cmd_line = unicode(a[1].strip())

                            if cmd_line.lower() in self.call_list.keys():
                                self.function_commands[lirc_cmd] = cmd_line

                            elif (len(a) > 1) and cmd_line.lower()[0:8] == 'command:':
                                self.external_commands[lirc_cmd] =cmd_line[8:].strip()
                                self.external_commands_lower[lirc_cmd.lower()] = self.external_commands[lirc_cmd]

                            elif (len(a) > 1) and cmd_line.lower()[0:5] == 'bash:':
                                self.shell_commands[lirc_cmd] = []
                                quote_cnt = 0
                                quote_cmd = ''
                                word_cmd = ''
                                aa = cmd_line[5:].strip()
                                for c in range(len(aa)):
                                    if quote_cnt == 1:
                                        if aa[c] == '"':
                                            self.shell_commands[lirc_cmd].append(quote_cmd)
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
                                        self.shell_commands[lirc_cmd].append(word_cmd)
                                        word_cmd = ''

                                self.shell_commands_lower[lirc_cmd.lower()] = self.shell_commands[lirc_cmd]

                            else:
                                log.log('Ignoring Lirc line in config file %s: %r\n' % (file, line))

                        except:
                            log.log('Invalid Lirc line in config file %s: %r\n' % (file, line))
                            log.log(traceback.format_exc())
                            continue

                elif plugin in range(self.plugin_count):
                    self.pi_conf[plugin].validate_config_line(type, line)

            except Exception as e:
                log.log(u'Error reading Config\n')
                log.log(traceback.format_exc())
                continue

        f.close()

        return True

    # end read_config()

    def validate_commandline(self):
        """Read the commandline and validate the values"""
        if self.read_commandline() == 0:
             return(0)

        if self.args.version:
            print("The Netherlands (%s)" % self.version(True))
            for p in range(self.plugin_count):
                print("The Netherlands (%s)" % self.pi_conf[p].version(True))

            return(0)

        if self.args.description:
            print("The Netherlands (%s)" % self.version(True))
            for p in range(self.plugin_count):
                print("The Netherlands (%s)" % self.pi_conf[p].version(True))

            print(description_text)
            return(0)

        for p in range(self.plugin_count):
            x = self.pi_conf[p].commandline_queries(self.args, self.opt_dict)
            if x != None:
                return(x)

        conf_read = self.read_config()
        if self.args.verbose != None:
            self.opt_dict['verbose'] = self.args.verbose
            log.verbose = self.opt_dict['verbose']

        if 'log_level' in self.opt_dict.keys():
            log.log_level = self.opt_dict['log_level']

        # Opening the logfile
        if self.args.log_file != None and os.access(self.args.log_file, os.W_OK):
            log_file = self.args.log_file

        elif 'log_file' in self.opt_dict.keys() and os.access(self.opt_dict['log_file'], os.W_OK):
            log_file = self.opt_dict['log_file']

        else:
            log_file = self.log_file

        if self.args.log_file != None and log_file != self.args.log_file:
            log.log('1Error opening supplied logfile: %s. \nCheck permissions! Falling back to %s\n' % (self.args.log_file, log_file), 0)

        elif 'log_file' in self.opt_dict.keys() and log_file != self.opt_dict['log_file']:
            log.log('2Error opening supplied logfile: %s. \nCheck permissions! Falling back to %s\n' % (self.opt_dict['log_file'], log_file), 0)

        self.log_file = log_file
        log.open_stderr_filehandles()
        log.start()
        if self.args.case_sensitive != None:
            self.opt_dict['case_sensitive'] = self.args.case_sensitive

        if self.args.fifo_file != None:
            self.opt_dict['fifo_file'] = self.args.fifo_file

        if self.args.lirc_id != None:
            self.opt_dict['lirc_id'] = self.args.lirc_id

        for p in range(self.plugin_count):
            x = self.pi_conf[p].validate_options(self.args)
            if x != None:
                return(x)

            for k, v in self.pi_conf[p].opt_dict.items():
                if k not in self.opt_dict.keys():
                    self.opt_dict[k] = v

        for p in range(self.plugin_count):
            for k, v in self.opt_dict.items():
                if k not in self.opt_dict.keys():
                    self.pi_conf[p].opt_dict[k] = v

        self.write_opts_to_log()
        if self.args.configure:
            self.write_config(False)
            return(0)

        if self.args.save_options:
            self.write_config(True)
            return(0)

        for p in range(self.plugin_count):
            x = self.pi_conf[p].final_validation()
            if x != None:
                return(x)

    # end validate_commandline()

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
            log.log('Error creating fifo-file: %s\n' % self.opt_dict['fifo_file'],0)
            log.log(traceback.format_exc())

        os.umask(tmpval)
        start = FiFo_Activator(self.opt_dict['fifo_file'], 'fifo')
        start.start()

        # Opening the read handle to the fifo
        try:
            self.fifo_read = config.open_file(self.opt_dict['fifo_file'], mode = 'rb', buffering = None)

        except:
            log.log('Error reading fifo-file: %s\n' % self.opt_dict['fifo_file'],0)
            log.log(traceback.format_exc())
            return(1)

        # Opening the write handle to the fifo
        try:
            self.fifo_write = config.open_file(self.opt_dict['fifo_file'], mode = 'wb', buffering = None)

        except:
            log.log('Error writing to fifo-file: %s\n' % self.opt_dict['fifo_file'],0)
            log.log(traceback.format_exc())
            return(1)
    # end open_fifo_filehandles()

    def start_ircat(self):
        if call(['pgrep', 'lircd']) != 0:
            log.log('No lirc daemon found, so not starting ircat\n', 1)

        else:
            self.ircat_pid = Popen(["/usr/bin/ircat", self.opt_dict['lirc_id']], stdout = self.fifo_write, stderr = log.stderr_write)

    # end start_ircat()

    def write_opts_to_log(self):
        """
        Save the the used options to the logfile
        """
        if log.log_output == None:
            return(0)

        log.log(u'',1, 2)
        log.log(u'Starting lircradio',1, 2)
        log.log(u'Python versie: %s.%s.%s' % (sys.version_info[0], sys.version_info[1], sys.version_info[2]),1, 2)
        log.log(u'The Netherlands (%s)' % self.version(True), 1, 2)
        log.log(u'log level = %s' % (log.log_level), 1, 2)
        log.log(u'config_file = %s' % (self.args.config_file), 1, 2)
        log.log(u'verbose = %s\n' % self.opt_dict['verbose'], 1, 2)
        log.log(u'fifo_file = %s\n' % self.opt_dict['fifo_file'], 1, 2)
        log.log(u'lirc_id = %s\n' % self.opt_dict['lirc_id'], 1, 2)
        log.log(u'case_sensitive = %s\n' % self.opt_dict['case_sensitive'], 1, 2)
        log.log(u'',1, 2)
        for p in range(self.plugin_count):
            self.pi_conf[p].write_opts_to_log()

    # end write_opts_to_log()

    def write_config(self, copy_old = False):
        """
        Save the channel info and the default options
        if copy_old is True we only create the Configuration section and copy over the other sections
        if copy_old is False we create all section afresh
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
        f.write(u'[%s]\n' % self.__CONFIG_SECTIONS__[-1][1])
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
        f.write(u'log_file = %s\n' % self.log_file)
        f.write(u'log_level = %s\n' % log.log_level)
        f.write(u'verbose = %s\n' % self.opt_dict['verbose'])
        f.write(u'\n')
        f.write(u'fifo_file = %s\n' % self.opt_dict['fifo_file'])
        f.write(u'lirc_id = %s\n' % self.opt_dict['lirc_id'])
        f.write(u'# Turning "case_sensitive" off will convert all commands comming through\n')
        f.write(u'# the pipe and all internal commands to lowercase\n')
        f.write(u'case_sensitive = %s\n' % self.opt_dict['case_sensitive'])
         #f.write(u' = %s\n' % self.opt_dict[''])
        for p in range(self.plugin_count):
            self.pi_conf[p].write_opts_to_config(f)

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
        f.write(u'# These are handled in the bash script: `~/.ivtv/Commands.sh`\n')
        f.write(u'# You can also move that script for global access to `/usr/bin`\n')
        f.write(u'# Numerical commands you can not set here, they are always translated to\n')
        f.write(u'# a channelchange in the radioFunctions plugin.\n')
        f.write(u'# If you have "case_sensitive" turned off all commands comming through\n')
        f.write(u'# the pipe and all internal commands will convert to lowercase\n')
        f.write(u'# So will any you put here\n')
        f.write(u'# Of course any COMMAND or BASH command as described below stays case-sensitive!\n')
        f.write(u'\n')
        for p in range(self.plugin_count):
            if len(self.pi_conf[p].functioncalls) > 0:
                self.pi_conf[p].add_command_help(f)

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
        f.write(u'\n')
        f.write(u'[%s]\n' % self.__CONFIG_SECTIONS__[-1][2])
        for c, command in self.function_commands.items():
            f.write(u'%s = %s\n' % (c, command))

        for c, command in self.external_commands.items():
            f.write(u'%s = COMMAND:%s\n' % (c, command))

        for c, command in self.shell_commands.items():
            line = u'%s = BASH:' % c
            for cc in command:
                if ' ' in cc:
                    line = u'%s "%s"' % (line, cc)

                else:
                    line = u'%s %s' % (line, cc)

            line = re.sub('\n', '', line)
            line = u'%s\n' % line
            f.write(line)

        f.write(u'\n')

        for p in range(self.plugin_count):
            for s in self.pi_conf[p].__CONFIG_SECTIONS__.keys():
                self.pi_conf[p].write_config_section(f, s, copy_old)

        f.close()
        return True

    # end write_config()

    def close(self):
        # close everything neatly
        for p in range(self.plugin_count):
            if len(self.pi_conf[p].functioncalls) > 0:
                self.pi_conf[p].close()

        if self.ircat_pid != None:
            self.ircat_pid.kill()

        if self.fifo_write != None:
            self.fifo_write.write('quit\n')
            self.fifo_write.close()
            self.fifo_write = None

        if self.fifo_read != None:
            self.fifo_read.close()
            self.fifo_read = None

        if os.access(self.opt_dict['fifo_file'], os.F_OK):
            os.remove(self.opt_dict['fifo_file'])

        if log.stderr_write != None:
            for p in range(config.plugin_count):
                config.pi_conf[p].stderr_write = None

            log.stderr_write.write('quit\n')
            log.stderr_write.close()
            log.stderr_write = None

        if log.stderr_listner != None:
            log.stderr_listner.join()

        if log.stderr_read != None:
                log.stderr_read.close()
                log.stderr_read = None

        if log.stderr_fifo != None and os.access(log.stderr_fifo, os.F_OK):
            os.remove(log.stderr_fifo)
        log.stderr_listner = None
        log.log_queue.put('quit')

    # end close()

# end Configure
config = Configure()

class FiFo_Activator(Thread):
    def __init__(self, fifo, name):
        Thread.__init__(self)
        self.fifo = fifo
        self.name = name

    def run(self):
        fp = '/tmp/' + pwd.getpwuid(os.getuid())[0] + '-' + self.name + '-start.sh'
        if os.access(fp, os.F_OK):
            os.remove(fp)

        f =io.open(fp, 'wb')
        f.write('#!/bin/bash\n')
        f.write('echo "start" > %s\n' % self.fifo)
        f.write('\n')
        f.close()
        os.chmod(fp, 0700)
        call([fp])
        time.sleep(1)
        os.remove(fp)

# end FiFo_Activator()

class Listen_to_StdErr(Thread):
    def __init__(self):
        Thread.__init__(self)
        # Checking out the fifo file
        try:
            tmpval = os.umask(0115)
            for f in (log.stderr_fifo,):
                if os.access(f, os.F_OK):
                    if not S_ISFIFO(os.stat(f).st_mode):
                         os.remove(f)
                         os.mkfifo(f, 0662)

                    if not os.access(f, os.R_OK):
                        os.chmod(f, 0662)

                else:
                    os.mkfifo(f, 0662)

        except:
            log.log('Error creating stderr_fifo: %s\n' % log.stderr_fifo, 0)
            log.log(traceback.format_exc())

        os.umask(tmpval)

    def run(self):
        byteline = ''
        byte = ''
        try:
            while True:
                try:
                    if log.stderr_read != None:
                        byte = log.stderr_read.readline(1)

                except:
                    pass

                if byte == None or (byte == '\n' and byteline == '') or (byte == ' ' and byteline == ''):
                    continue

                elif byte != '\n':
                    byteline += byte
                    continue

                elif byteline.strip().lower() == 'start':
                    log.log('Starting stderr Listener on %s\n'% log.stderr_fifo, 1)
                    byteline = ''
                    continue

                elif byteline.strip().lower() == 'quit' or self.quit:
                    log.log('Closing stderr Listener on %s\n'% log.stderr_fifo, 1)
                    return(0)

                log.log('%s\n' % byteline)
                byteline = ''

        except:
            log.log('\nAn unexpected error has occured:\n', 0)
            log.log(traceback.format_exc())
            log.log('\nIf you want assistence, please attach your configuration and log files!\n     %s\n     %s\n' % (config.config_file, config.log_file),0)
            return(99)

        log.log('Closing stderr Listener on %s\n'% log.stderr_fifo, 1)

# end Listen_to_StdErr()

class Listen_To(Thread):
    """
    Listening Thread to the fifo pipe
    """
    def __init__(self, fifo):
        Thread.__init__(self)
        self.quit = False
        self.fifo = fifo

    def run(self):
        internal_cmds = {}
        if config.opt_dict['case_sensitive']:
            for k, c in config.function_commands.items():
                if c == config.call_list[c.lower()]['function']:
                    internal_cmds[k] = config.call_list[c.lower()]

            external_cmds = config.external_commands
            bash_cmds = config.shell_commands

        else:
            for k, c in config.function_commands.items():
                internal_cmds[k.lower()] = config.call_list[c.lower()]

            external_cmds = config.external_commands_lower
            bash_cmds = config.shell_commands_lower

        byteline = ''
        try:
            while True:
                try:
                    byte = self.fifo.readline(1)

                except:
                    return(0)

                if self.quit:
                    return(0)

                if byte == None or (byte == '\n' and byteline == '') or (byte == ' ' and byteline == ''):
                    continue

                elif byte != '\n' and  byte != ' ':
                    byteline += byte
                    continue

                elif byteline.strip().lower() == 'start':
                    log.log('Starting Command Listener on %s\n'% config.opt_dict['fifo_file'], 1)
                    byteline = ''
                    continue

                elif byteline.strip().lower() == 'quit' or self.quit:
                    log.log('%s command received.\n' % byteline, 2)
                    return(0)

                elif re.match('([0-9]+)', byteline.strip()):
                    chan = int(re.match('([0-9]+)', byteline.strip()).group(0))
                    log.log('%s command received.\n' % byteline, 2)
                    #~ rfcalls().select_channel(int(re.match('([0-9]+)', byteline.strip()).group(0)))
                    byteline = ''
                    continue

                if not config.opt_dict['case_sensitive']:
                    byteline = byteline.lower()

                if byteline.strip() in internal_cmds.keys():
                    log.log('%s command received.\n' % byteline, 2)
                    pi_cmd = internal_cmds[byteline.strip()]['function']
                    pi_num = internal_cmds[byteline.strip()]['plugin']
                    if pi_num == -1:
                        if pi_cmd == 'PowerOff'and config.command_name != None:
                            log.log('Executing %s %s' % (config.command_name, 'poweroff'), 32)
                            call([config.command_name,'poweroff'])

                        elif pi_cmd == 'Reboot'and config.command_name != None:
                            log.log('Executing %s %s' % (config.command_name, 'reboot'), 32)
                            call([config.command_name,'reboot'])

                        elif pi_cmd == 'Hibernate'and config.command_name != None:
                            log.log('Executing %s %s' % (config.command_name, 'hibernate'), 32)
                            for p in range(config.plugin_count):
                                config.pi_func[p]().rf_function_call(pi_cmd)

                            call([config.command_name,'hibernate'])

                        elif pi_cmd == 'Suspend'and config.command_name != None:
                            log.log('Executing %s %s' % (config.command_name, 'suspend'), 32)
                            for p in range(config.plugin_count):
                                config.pi_func[p]().rf_function_call(pi_cmd)

                            call([config.command_name,'suspend'])

                    elif pi_num in range(config.plugin_count):
                        config.pi_func[pi_num]().rf_function_call(pi_cmd)

                    byteline = ''

                elif byteline.strip() in external_cmds.keys():
                    log.log('%s command received.\n' % byteline, 2)
                    call([config.command_name,external_cmds[byteline.strip()]])
                    byteline = ''

                elif byteline.strip() in bash_cmds.keys():
                    log.log('%s command received.\n' % byteline, 2)
                    call(bash_cmds[byteline.strip()])
                    byteline = ''

                else:
                    log.log('Unregognized %s command received.\n' % byteline, 4)
                    byteline = ''

        except:
            log.log('\nAn unexpected error has occured:\n', 0)
            log.log(traceback.format_exc())
            log.log('\nIf you want assistence, please attach your configuration and log files!\n     %s\n     %s\n' % (config.config_file, config.log_file),0)
            return(99)

# end Listen_To()

def main():
    # We want to handle unexpected errors nicely. With a message to the log
    try:
        # Get the options, channels and other configuration

        x = config.validate_commandline()
        print x
        if x != None:
            return(x)

        log.log( 'Starting Lirc Listener on lircID: %s\n'% config.opt_dict['lirc_id'])
        config.open_fifo_filehandles()
        config.start_ircat()

        listener = Listen_To(config.fifo_read)
        listener.start()
        log.log( 'To QUIT: echo "quit" to %s\n'% config.opt_dict['fifo_file'])

        listener.join()
        log.log( 'Closing down\n',1)
        if config.ircat_pid != None:
            config.ircat_pid.kill()

    except:
        log.log('\nAn unexpected error has occured:\n', 0)
        log.log(traceback.format_exc())
        log.log('\nIf you want assistence, please attach your configuration and log files!\n     %s\n     %s\n' % (config.config_file, config.log_file),0)
        return(99)

    # and return success
    return(0)
# end main()

# allow this to be a module
if __name__ == '__main__':
    x = main()
    config.close()
    sys.exit(x)
