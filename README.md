Overview
========
This is a python WSGI application that prints the DNS SRV records used
for XMPP. You can see it running at https://kingant.net/check_xmpp_dns/

Available at https://github.com/markdoliner/check_xmpp_dns


Dependencies
============
* python dns library.
  * Homepage: http://www.dnspython.org/
  * Ubuntu: apt-get install python-dnspython
* (optional) python gevent library. Only needed if you execute the
  script directly to run a standalone web server.
  * Homepage: http://www.gevent.org/
  * Ubuntu: apt-get install python-gevent
* (optional) gunicorn. Only needed if you want to use the included upstart or systemd service
  * install: apt-get install gunicorn
  * upstart: check-xmpp-dns.conf upstart config to run the script as a system service.
  * systemd: (be sure paths, user and permissions are set properly). 
  copy check_xmpp_dns.service to /etc/systemd/system/check_xmpp_dns.service
  copy tmpfiles.d_gunicorn.conf to /etc/tmpfiles.d/gunicorn.conf 

Usage
=====
This script's main method starts a standard HTTP server on port 1000 using
the gevent WSGI server. You may wish to proxy traffic to this port from
another web server. You can use the included check-xmpp-dns.conf upstart
config file or systemd service to run the script as a system service.

Or you can use any other WSGI server to start the script's 'application'
method.
