Overview
========

This is a python cgi script that prints the DNS SRV records used for
XMPP. You can see it running at https://kingant.net/check_xmpp_dns/

Available at https://github.com/markdoliner/check_xmpp_dns


Requirements
============
* python dns library.
  * Homepage: http://www.dnspython.org/
  * Ubuntu: apt-get install python-dnspython
* python gevent library for the web server, but you can rip this out
  if you want to run it some other way.


Usage
=====
This script's main method starts a standard HTTP server on port 1000 using
the gevent WSGI server. My web server is configured to route traffic for
/check_xmpp_dns/ to this port.

But you don't have to run it this way. You can use any server with WSGI
support to start the scripts 'application' method.
