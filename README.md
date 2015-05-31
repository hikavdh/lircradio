# lircradio
A daemon script to pipe commands from lirc or from outside through ssh to for instance ivtv-radio or to suspend

## Recuirements

 * Python 2.6 or 2.7
 * Lirc
 * Alsa
 * [pyalsaaudio 0.7](http://sourceforge.net/projects/pyalsaaudio/)
 * [ivtv-utils](http://www.ivtvdriver.org/)
 * [v4l-utils](http://git.linuxtv.org/v4l-utils.git)
 * It also looks for either [pm-utils](http://pm-utils.freedesktop.org/) or the [TuxOnIce hibernate scripts](http://www.tuxonice.net/) for suspend/hibernate functionality 

## The idea

The original idea last september was to be able to control an instance of ivtv-radio through Lirc. After some searching my eye fell on ircat, part off the Lirc suite. It listens lo lirc and prints the commands to stdout.  
At first I was thinking in simple bash, which is mainly linear. So I had to separate ircat from the script to handle the commands, so a fifo pipe came into view. Ircat on the one side puts the commands it receives in there and on the other side sits a `while True` loop listening to what comes through.
When working on the idea I soon discovered the idea was even more usefull then I at first thought. On the one side, not only ircat could put commands in the pipe, but any script or you could echo it there yourself. On the other side, it was not limited to controling the radio. And very nice; if you this way suspend a machine remotely through ssh, your console won't lock-up. The command is 100% running on the remote machine.  

Around the same time I discovered Python. A wonderfull language, made for me. In the last months since november last year, I learned the language by rewritting the allready two years unmaintained [tv_grab_nl_py](https://github.com/tvgrabbers/tvgrabnlpy) project. Making it 10 times more powerfull. Now it is starting to go to maintainance mode.  
Since my original bash script was not as stable as I would want, I started to rewrite it in Python. You're looking at the first result. It's still a bit crude, but working. In the comming week I will add further documentation. In the comming weeks I will update on installation and the ability to run without ivtv/v4l installed. I also will further test everything. If anybody would want to help me with runscripts for other environments then open-rc on Gentoo? Also suggestions/requests are welcom.

Hika, Utrecht 31 may 2015


