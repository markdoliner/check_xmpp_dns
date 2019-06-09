Overview
========
This is a python WSGI application that prints the DNS SRV records used
for XMPP. You can see it running at https://kingant.net/check_xmpp_dns/

Source available at https://github.com/markdoliner/check_xmpp_dns


Dependencies
============
* python dns library. Use to query DNS servers directly.
  * Homepage: http://www.dnspython.org/
  * On Ubuntu: apt-get install python3-dnspython
* python jinja2 library. Used to render the HTML templates.
  * Homepage: http://jinja.pocoo.org/
  * On Ubuntu: apt-get install python3-jinja2
* (optional) python gevent library. Only needed if you execute the
  script directly to run a standalone web server.
  * Homepage: http://www.gevent.org/
  * On Ubuntu: apt-get install python3-gevent
* (optional) gunicorn3. Only needed if you want to use the included systemd service
  * On Ubuntu: apt-get install gunicorn3
  * (be sure paths, user and permissions are set properly). \
    Copy `check_xmpp_dns.service` to `/etc/systemd/system/check_xmpp_dns.service`
    and copy `tmpfiles.d_gunicorn.conf` to `/etc/tmpfiles.d/gunicorn.conf`


Local development
=================
It's easy to run the application locally:
```
virtualenv venv
. venv/bin/activate
pip install -r requirements.txt
./check_xmpp_dns.py
```
Then open http://localhost:1000/ in a web browser.


How to deploy to a real server
==============================
While you _can_ use the "local development" steps above to run the
script on a real server, it's wise to run it as a service, instead.

See the notes about gunicorn3 in the dependency section above for
some rough instructions on running the script as a systemd service.

Another option is to run the script directly. It starts a plain HTTP
server on port 1000 using the gevent WSGI server. You could proxy
traffic to this port from another web server.

Or you can use any other WSGI server to start the script's 'application'
method.
