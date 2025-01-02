Overview
========
This is a python ASGI application that prints the DNS SRV records used
for XMPP. You can see it running at https://kingant.net/check_xmpp_dns/

Source available at https://github.com/markdoliner/check_xmpp_dns


Dependencies
============
* Python dns library. Use to query DNS servers directly.
  * Homepage: http://www.dnspython.org/
* Python jinja library. Used to render the HTML templates.
  * Homepage: https://jinja.palletsprojects.com/
* Python Starlette library.
  * Homepage: http://www.gevent.org/
* (optional) Uvicorn. Only needed if you want to use the included systemd service
  * On Ubuntu: apt-get install gunicorn3
  * TODO MARK: Update the service and tmpfiles thing for uvicorn. Or Docker.
  * (be sure paths, user and permissions are set properly). \
    Copy `check_xmpp_dns.service` to `/etc/systemd/system/check_xmpp_dns.service`
    and copy `tmpfiles.d_gunicorn.conf` to `/etc/tmpfiles.d/gunicorn.conf`


Local Development
=================
First-time setup:
1. Install Poetry. The steps for doing so are system-dependent. One option on macOS is `brew
install poetry`
2. ```
poetry install --no-root --with=dev
```

To run a local server that automatically reloads when code changes, run:
```
make run-local
```
Then open http://localhost:8000/ in a web browser.


Running in Production
=====================
I suggest running as a Docker container.

To build the Docker image:
```
make docker
```

To run the Docker image:
```
make run-docker
```

It uses the Uvicorn ASGI server. If you wish to use another ASGI server you'll have to figure out
the steps yourself.

The application does not configure Python logging itself. It's expected that the ASGI will do this.
Uvicorn _does_ configure logging, and writes various information to stdout.

The application records each hostname that was searched for in
/var/log/check-xmpp-dns/requestledger.txt
You can bind mount this directory and collect the logs, do log rotation, etc.
